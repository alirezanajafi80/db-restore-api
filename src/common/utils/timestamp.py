from datetime import datetime
import pytz

tehran_tz = pytz.timezone('Asia/Tehran')


class DatetimeUtil:

    @staticmethod
    def utc_now_datetime() -> datetime:
        utc_now = datetime.utcnow().replace(tzinfo=pytz.utc)
        tehran_now = utc_now.astimezone(tehran_tz)
        return tehran_now

    @staticmethod
    def utc_now_datetime_str() -> str:
        return DatetimeUtil.utc_now_datetime().strftime("%Y%m%d_%H%M")
