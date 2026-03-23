from pydantic import BaseModel


class LoginQRInfo(BaseModel):
    QRImage: str
    DeepLink: str
    IsHK: bool = False
    IsRecaptcha: bool = False
    RecaptchaV2PublicKey: str = ""
    IsOTP: bool = False


class CheckLoginStatus(BaseModel):
    Result: int
    ResultCode: int
    ResultMessage: str


class BeanfunAccountInfo(BaseModel):
    account_hidden: str
    point: str


class HeartBeatResponse(BaseModel):
    ResultCode: int
    ResultDesc: str
    MainAccountID: str


class GamePointResponse(BaseModel):
    RemainPoint: str
    ResultCode: int
    ResultDesc: str


class MSAccountModel(BaseModel):
    account_name: str
    account: str
    sn: str
