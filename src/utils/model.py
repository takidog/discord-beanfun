from pydantic import BaseModel


class LoginQRInfo(BaseModel):
    strEncryptData: str


class CheckLoginStatus(BaseModel):
    ResultData: None | dict
    Result: int
    ResultMessage: str


class BeanfunAccountInfo(BaseModel):
    account_hidden: str
    point: str


class HeartBeatResponse(BaseModel):
    ResultData: None | dict
    Result: int
    ResultMessage: str


class GamePointResponse(BaseModel):
    RemainPoint: str
    ResultCode: int
    ResultDesc: str


class MSAccountModel(BaseModel):
    account_name: str
    account: str
    sn: str
