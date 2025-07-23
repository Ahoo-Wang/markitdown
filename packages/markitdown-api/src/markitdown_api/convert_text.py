from io import BytesIO
from typing import Any

from fastapi import APIRouter
from pydantic import Field

from markitdown import StreamInfo, DocumentConverterResult
from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import (
    ConvertRequest,
    StreamMetadata,
    ConvertResponse,
    MarkdownResponse,
)

TAG = "Convert Text"


class ConvertTextRequest(ConvertRequest):
    text: str = Field(min_length=1, description="Text to convert")
    mimetype: str = Field(
        default="text/plain", description="MIME type of the input text"
    )


class TextApiConverter(ApiConverter):
    def __init__(self, request: ConvertTextRequest):
        super().__init__(request)

    def _internal_convert(self, **kwargs: Any) -> DocumentConverterResult:
        text_binary = self.request.text.encode("utf-8")
        text_binary = """
        <!doctype lake><meta name="doc-version" content="1" /><meta name="viewport" content="fixed" /><meta name="typography" content="classic" /><meta name="paragraphSpacing" content="relax" /><h1 data-lake-id="rnY0E" id="rnY0E"><span data-lake-id="u4bb64c40" id="u4bb64c40">查看积分流水</span></h1><h2 data-lake-id="Oq5KV" id="Oq5KV"><span data-lake-id="u8279283c" id="u8279283c">用户查看自身账户积分流水信息</span></h2><ol list="u10b386c0"><li fid="u6de94eea" data-lake-id="u38920f5e" id="u38920f5e"><span data-lake-id="u900b7cbf" id="u900b7cbf">进入交易平台，进入我的买道</span></li><li fid="u6de94eea" data-lake-id="ub7d69c8c" id="ub7d69c8c"><span data-lake-id="u5670e7f1" id="u5670e7f1">点击资产中心下我的积分</span></li><li fid="u6de94eea" data-lake-id="ud3f58ac6" id="ud3f58ac6"><span data-lake-id="uf46a2878" id="uf46a2878">可在该页面下查看可用积分、冻结积分以及积分流水</span></li></ol><h2 data-lake-id="K5c9q" id="K5c9q"><span data-lake-id="ucede9213" id="ucede9213">CRM平台查看积分流水</span></h2><ol list="u6601c8a8"><li fid="u05b6a833" data-lake-id="u4a046068" id="u4a046068"><span data-lake-id="uf7326fd6" id="uf7326fd6">客服登录CRM平台，进入客户账户管理下积分账户</span></li><li fid="u05b6a833" data-lake-id="u2d16ad12" id="u2d16ad12"><span data-lake-id="u799e2e18" id="u799e2e18">搜索指定客户名称，点击查看积分流水</span></li></ol><h1 data-lake-id="OHKcp" id="OHKcp"><span data-lake-id="u9001a6b8" id="u9001a6b8">获取积分的方式</span></h1><h2 data-lake-id="RLMq3" id="RLMq3"><span data-lake-id="u4b8574a3" id="u4b8574a3">注册获取积分</span></h2><p data-lake-id="u33a74c92" id="u33a74c92"><span data-lake-id="u5950d02f" id="u5950d02f">新注册客户可获赠99积分</span></p><h2 data-lake-id="vW6qP" id="vW6qP"><span data-lake-id="u5fe2dda5" id="u5fe2dda5">客服赠送积分</span></h2><ol list="u637300c4"><li fid="u05b6a833" data-lake-id="u02c3bf6c" id="u02c3bf6c"><span data-lake-id="udc09955a" id="udc09955a">客服登录CRM平台，进入客户账户管理下积分账户</span></li><li fid="u05b6a833" data-lake-id="ud1ead5e1" id="ud1ead5e1"><span data-lake-id="ua2ee8c38" id="ua2ee8c38">搜索指定客户名称，点击赠送积分</span></li><li fid="u05b6a833" data-lake-id="u4d312e2b" id="u4d312e2b"><span data-lake-id="u823882d1" id="u823882d1">填写赠送积分数和赠送备注，点击提交</span></li><li fid="u05b6a833" data-lake-id="u89e0ae25" id="u89e0ae25"><span data-lake-id="u1ad9c81d" id="u1ad9c81d">赠送成功</span></li></ol><h1 data-lake-id="X4Obd" id="X4Obd"><span data-lake-id="u453dc5a8" id="u453dc5a8">积分使用规则</span></h1><ol list="u44052693"><li fid="u9a12afba" data-lake-id="ud6cda90b" id="ud6cda90b"><span data-lake-id="uff70a383" id="uff70a383">只可用于自营订单</span></li><li fid="u9a12afba" data-lake-id="u12179694" id="u12179694"><span data-lake-id="u3236df1a" id="u3236df1a">积分可抵扣订单结算金额的2%</span></li></ol>
        """.encode(
            "utf-8"
        )
        self.metadata = StreamMetadata(
            mimetype=self.request.mimetype,
            data_size=len(text_binary),
        )
        binary_io = BytesIO(text_binary)

        stream_info = StreamInfo(
            mimetype=self.request.mimetype, charset=self.request.charset
        )
        return self.markitdown.convert_stream(
            stream=binary_io, stream_info=stream_info, **kwargs
        )


router = APIRouter(
    prefix="/convert/text",
    tags=[TAG],
)


@router.post(path="", response_model=ConvertResponse)
async def convert_text(request: ConvertTextRequest):
    return TextApiConverter(request).convert()


@router.post(path="/markdown", response_class=MarkdownResponse)
async def convert_uri_markdown(request: ConvertTextRequest):
    return TextApiConverter(request).convert().result.markdown
