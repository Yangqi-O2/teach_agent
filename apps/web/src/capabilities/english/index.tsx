import type { CapabilityModule } from "../registry";
import { EnglishPage } from "./page";

const capability: CapabilityModule = {
  id: "english",
  routes: [{ path: "/cap/english", element: <EnglishPage /> }],
};

export default capability;
