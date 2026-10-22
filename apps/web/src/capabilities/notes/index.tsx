import type { CapabilityModule } from "../registry";
import { NotesPage } from "./page";

const capability: CapabilityModule = {
  id: "notes",
  routes: [{ path: "/cap/notes", element: <NotesPage /> }],
};

export default capability;
