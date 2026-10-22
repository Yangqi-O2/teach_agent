import type { CapabilityModule } from "../registry";
import { WechatDigestPage } from "./page";

const capability: CapabilityModule = {
  id: "wechat_digest",
  routes: [{ path: "/cap/wechat-digest", element: <WechatDigestPage /> }],
};

export default capability;
