from pydantic import BaseModel


class LoginQRInfo(BaseModel):
    strEncryptData: str
    strEncryptBCDOData: str


class CheckLoginStatus(BaseModel):
    Result: int
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
