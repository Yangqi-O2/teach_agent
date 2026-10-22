import {
  AlertCircle,
  ArrowUpRight,
  BookOpen,
  Brain,
  Calendar,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ClipboardPaste,
  Clock,
  Command,
  Cpu,
  Database,
  Download,
  FileText,
  FolderOpen,
  GraduationCap,
  History,
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
  UserPlus,
  UserRound,
  Users,
  LogOut,
  Shield,
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
  "chevron-down": ChevronDown,
  command: Command,
  x: X,
  "refresh-cw": RefreshCw,
  play: Play,
  square: Square,
  clock: Clock,
  database: Database,
  download: Download,
  history: History,
  "clipboard-paste": ClipboardPaste,
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
  users: Users,
  "user-round": UserRound,
  "user-plus": UserPlus,
  "log-out": LogOut,
  shield: Shield,
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
