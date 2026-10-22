import {
  AlertCircle,
  ArrowUpRight,
  BookOpen,
  Brain,
  Calendar,
  Check,
  ChevronRight,
  CircleHelp,
  Clock,
  Command,
  Cpu,
  Database,
  FileText,
  FolderOpen,
  GraduationCap,
  KeyRound,
  LayoutDashboard,
  Library,
  Lightbulb,
  ListChecks,
  Loader2,
  MessageSquare,
  Monitor,
  Moon,
  NotebookPen,
  Palette,
  PencilLine,
  Play,
  Plus,
  Presentation,
  Radar,
  RefreshCw,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Sun,
  Target,
  Trash2,
  Type,
  Upload,
  Wand2,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "../lib/utils";

const MAP: Record<string, LucideIcon> = {
  "notebook-pen": NotebookPen,
  "book-open": BookOpen,
  "message-square": MessageSquare,
  radar: Radar,
  brain: Brain,
  "pencil-line": PencilLine,
  "layout-dashboard": LayoutDashboard,
  library: Library,
  "graduation-cap": GraduationCap,
  sparkles: Sparkles,
  settings: Settings,
  search: Search,
  plus: Plus,
  upload: Upload,
  "trash-2": Trash2,
  check: Check,
  "alert-circle": AlertCircle,
  "loader-2": Loader2,
  moon: Moon,
  sun: Sun,
  monitor: Monitor,
  "chevron-right": ChevronRight,
  command: Command,
  x: X,
  "refresh-cw": RefreshCw,
  play: Play,
  square: Square,
  clock: Clock,
  database: Database,
  "key-round": KeyRound,
  cpu: Cpu,
  type: Type,
  palette: Palette,
  info: CircleHelp,
  "arrow-up-right": ArrowUpRight,
  "list-checks": ListChecks,
  "wand-2": Wand2,
  server: Server,
  "shield-check": ShieldCheck,
  "folder-open": FolderOpen,
  lightbulb: Lightbulb,
  target: Target,
  calendar: Calendar,
  "file-text": FileText,
  presentation: Presentation,
};

export function getIcon(name?: string | null): LucideIcon {
  if (!name) return Sparkles;
  return MAP[name] ?? Sparkles;
}

type IconProps = {
  name?: string | null;
  className?: string;
  strokeWidth?: number;
};

export function Icon({ name, className, strokeWidth = 1.8 }: IconProps) {
  const Component = getIcon(name);
  return <Component className={cn("h-5 w-5", className)} strokeWidth={strokeWidth} />;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin", className)} strokeWidth={2} />;
}
