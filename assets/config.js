// TMWD 扩展配置
// TID: content script DOM 消息通道的元素 ID（与 TMWebDriver.py 约定，勿改）
const TID = '__ljq_tmwd01';
// WS 服务器地址（与 TMWebDriver.py 的 host/port 一致）
const TMWD_WS_URL = 'ws://127.0.0.1:18765';
// 鉴权（#4）：服务端启用 token（token.txt 或 TMWD_TOKEN）时，在此填同一个值并重载扩展；
// 留空 = 服务端未启用鉴权时的默认。连接后首条消息发送 {type:'hello', token}
const TMWD_TOKEN = '';
