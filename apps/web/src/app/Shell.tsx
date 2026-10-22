import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useState, type ReactNode } from "react";

import { Icon } from "../components/Icon";
import { Toaster } from "../components/ui/overlay";
import { CommandPalette } from "./CommandPalette";
import { Sidebar, SidebarContent } from "./Sidebar";
import { Topbar } from "./Topbar";

function MobileDrawer({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="overlay-mask fixed inset-0 z-50 bg-ink/25 backdrop-blur-[2px] md:hidden" />
        <DialogPrimitive.Content className="drawer-in fixed inset-y-0 left-0 z-50 w-[280px] border-r border-line bg-surface shadow-lift focus:outline-none md:hidden">
          <DialogPrimitive.Title className="sr-only">导航</DialogPrimitive.Title>
          <div className="absolute right-2 top-4">
            <DialogPrimitive.Close asChild>
              <button className="rounded-lg p-2 text-ink-faint hover:bg-surface-2 hover:text-ink">
                <Icon name="x" className="h-4 w-4" />
              </button>
            </DialogPrimitive.Close>
          </div>
          <SidebarContent onNavigate={() => onOpenChange(false)} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <div className="grain min-h-screen">
      <div className="aurora" aria-hidden />
      <Sidebar />
      <MobileDrawer open={mobileOpen} onOpenChange={setMobileOpen} />
      <div className="md:pl-[268px]">
        <Topbar onMenu={() => setMobileOpen(true)} />
        <main className="mx-auto w-full max-w-[1180px] px-4 pb-24 pt-7 md:px-9">{children}</main>
      </div>
      <CommandPalette />
      <Toaster />
    </div>
  );
}
