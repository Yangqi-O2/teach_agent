import type { CapabilityModule } from "../registry";
import { LibraryPage } from "./page";

const capability: CapabilityModule = {
  id: "library",
  routes: [{ path: "/cap/library", element: <LibraryPage /> }],
};

export default capability;
