"""This module defines the core functionality of the API"""

from datetime import datetime
from datetime import timedelta
from io import BytesIO
from typing import Any
from typing import Dict
from typing import List, Optional
from typing import Union

from CleanEmonCore.models import EnergyData

from CleanEmonBackend.lib.DBConnector import fetch_data, fetch_document, create_document

from ..lib.DBConnector import adapter
from ..lib.DBConnector import get_last_value
from ..lib.DBConnector import get_view_daily_consumption
from ..lib.DBConnector import send_meta
from ..lib.authenticator_config import UserInDB, UserInDBDataClass
from ..lib.plots import plot_data

USERS_DB_NAME = "app_users"


def get_data(date: Optional[str], sensors: List[str] = None, db: str = None,
             keep_last_only: bool = False, down_sampling: bool = False) -> EnergyData:
    """Fetches and prepares the daily data that will be returned, filtering in the provided `sensors`.
    Note that there is no need to explicitly specify the "timestamp sensor", as it will always be included.

    date -- a valid date string in `YYYY-MM-DD` format
    sensors -- an inclusive list containing the values of interest
    """

    if keep_last_only:
        return get_last_value(db)
    raw_data = fetch_data(date, db=db, down_sampling=down_sampling).energy_data

    if sensors:
        if "timestamp" not in sensors:
            sensors.append("timestamp")

        filtered_data = []
        for record in raw_data:
            filtered_record = {sensor: value for sensor, value in record.items() if sensor in sensors}
            filtered_data.append(filtered_record)
        data = filtered_data
    else:
        data = raw_data
    if keep_last_only:
        data = data[-1:]  # remove all items except the last one
    return EnergyData(date, data)


def get_range_data(from_date: str, to_date: str, sensors: List[str] = None, db: str = None,
                   down_sampling: bool = False) -> Dict:
    """Fetches and prepares the range data that will be returned.

    from_date -- a valid date string in `YYYY-MM-DD` format
    to_date -- a valid date string in `YYYY-MM-DD` format. It MUST be chronologically greater or equal to `from_date`
    sensors -- an inclusive list containing the values of interest
    """

    # Define the range data schema
    # todo: maybe define a an appropriate solid dataclass?
    data = {
        "from_date": from_date,
        "to_date": to_date,
        "range_data": []
    }

    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")
    one_day = timedelta(days=1)

    # Concatenate energy data from multiple dates into a single list
    now = from_dt
    while now <= to_dt:
        now_str = now.strftime("%Y-%m-%d")
        daily_data = get_data(now_str, sensors, db=db, down_sampling=down_sampling)
        data["range_data"].append(daily_data)
        now += one_day

    return data


def get_plot(date: str, sensors: List[str] = None, db: str = None) -> BytesIO:
    """Fetches and plots the desired data. Returns the path of the resulting plot.

    date -- a valid date string in `YYYY-MM-DD` format
    sensors -- an inclusive list containing the values of interest
    """

    energy_data = get_data(date, sensors, db=db)

    return plot_data(energy_data, columns=sensors)


def get_date_consumption(date: str, simplify: bool, db: str = None):
    """Hardcoded fetch-prepare accumulator function that handles the daily KwH. Returns the daily consumption in kwh.

    Acts as an under-the-curve measurement by subtracting the lowest power measurement from the highest one.
    It's not given that the first record of the energy data will always contain valid power values and thus, the "first
    value" is actually searched and cherry-picked. Same goes for the "last valid value".

    date -- a valid date string in `YYYY-MM-DD` format
    simplify -- if true, returns a single value, not a JSON object
    """

    consumption = get_view_daily_consumption(date, db)
    if simplify:
        data = consumption
    else:
        data = {
            "consumption": consumption,
            "unit": "kwh"
        }

    return data


def get_dates_consumptions(start_day: str, end_day: str, db: str, summation: bool):
    return adapter.view_daily_consumptions_range(day_start=start_day, day_end=end_day, db=db, summation=summation)


def get_mean_consumption(date: str, db: str = None) -> float:
    """Hardcoded fetch-prepare function that returns the daily consumption over the size of the building.
    If the given building has no appropriate information (e.g. no "size" meta-data) -1 is being returned.

    Mean Consumption is calculated as:  daily_consumption_of_date  /  size_of_building

    date -- a valid date string in `YYYY-MM-DD` format
    """
    _size_field = "Household m2"  # Hardcoded field - get_meta is not intended to be used in this way

    consumption: float = get_date_consumption(date, simplify=True, db=db)

    if has_meta(_size_field, db):
        size = float(get_meta(_size_field, db))
        if size:
            return consumption / size
    return -1


def get_meta(field: str = None, db: str = None) -> Union[Dict, Any]:
    meta = adapter.fetch_meta(db=db)
    if not field:
        return meta
    else:
        if field in meta:
            return meta[field]
    return {}


def has_meta(field: str, db: str = None) -> bool:
    meta = get_meta(db=db)

    if field not in meta:
        return False

    value = meta[field]
    return value != "null"


def set_meta_field(field: str, meta: Union[int, float, bool, str, None], db: str):
    return send_meta(field, meta, db=db)


def fetch_account_info(username: str):
    return fetch_document(username, USERS_DB_NAME)


def create_account(account: UserInDB) -> bool:
    """
    @param account:
    @return: True if account created OK, false if the account creation failed
    """

    account.disabled = True

    user_dataclass = UserInDBDataClass(account.username,
                                       account.hashed_password,
                                       account.disabled
                                       )

    return create_document(document=account.username, db=USERS_DB_NAME,
                           data=user_dataclass) != ""  # If empty there was a problem


def get_preds_consumption(start_day: str, end_day: str, db: str, summation: bool):
    return adapter.get_pred_consumption(db=db, day_start=start_day, day_end=end_day, summation=summation)
