import type { CapabilityModule } from "../registry";
import { CampusPage } from "./page";

const capability: CapabilityModule = {
  id: "campus",
  routes: [{ path: "/cap/campus", element: <CampusPage /> }],
};

export default capability;
