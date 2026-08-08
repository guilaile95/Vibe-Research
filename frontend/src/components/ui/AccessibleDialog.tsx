import * as React from "react";
import { createPortal } from "react-dom";

interface AccessibleDialogBaseProps {
  open: boolean;
  onClose: () => void;
  describedBy?: string;
  children: React.ReactNode;
  className?: string;
  overlayClassName?: string;
  /** Preserve form input by default; enable only when the previous UI allowed backdrop dismissal. */
  closeOnOverlay?: boolean;
}

export type AccessibleDialogProps = AccessibleDialogBaseProps &
  (
    | {
        /** ID of a title element rendered by the dialog's children. */
        labelledBy: string;
        title?: React.ReactNode;
        showTitle?: boolean;
      }
    | {
        /** Content rendered as the dialog's accessible heading. */
        title: Exclude<React.ReactNode, null | undefined | boolean>;
        labelledBy?: undefined;
        showTitle?: true;
      }
  );

const FOCUSABLE =
  'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), iframe, object, embed, [contenteditable="true"], [tabindex]:not([tabindex="-1"])';

/**
 * Small dependency-free modal primitive used by pages that need a real dialog.
 * It deliberately owns keyboard/focus and document state so individual pages
 * cannot accidentally diverge in accessibility behaviour.
 */
export function AccessibleDialog({
  open,
  onClose,
  title,
  labelledBy,
  describedBy,
  children,
  className,
  overlayClassName,
  closeOnOverlay = false,
  showTitle = true,
}: AccessibleDialogProps) {
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLElement | null>(null);
  const onCloseRef = React.useRef(onClose);
  onCloseRef.current = onClose;
  const generatedTitleId = React.useId();
  const titleId = labelledBy ?? generatedTitleId;

  React.useEffect(() => {
    if (!open) return;

    triggerRef.current = document.activeElement as HTMLElement | null;
    const body = document.body;
    const previousOverflow = body.style.overflow;
    body.style.overflow = "hidden";

    // Inert siblings of the dialog host, preserving any prior values to restore.
    const host = dialogRef.current?.parentElement;
    const siblings = host?.parentElement
      ? Array.from(host.parentElement.children).filter((node) => node !== host)
      : [];
    const previousState = siblings.map((node) => ({
      node,
      inert: (node as HTMLElement).inert,
      ariaHidden: node.getAttribute("aria-hidden"),
    }));
    siblings.forEach((node) => {
      (node as HTMLElement).inert = true;
      node.setAttribute("aria-hidden", "true");
    });

    const focusInitial = () => {
      const root = dialogRef.current;
      if (!root) return;
      const first = root.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? root).focus();
    };
    const id = window.setTimeout(focusInitial, 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const root = dialogRef.current;
      if (!root) return;
      const focusable = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!focusable.length) {
        event.preventDefault();
        root.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);

    return () => {
      window.clearTimeout(id);
      document.removeEventListener("keydown", onKeyDown);
      body.style.overflow = previousOverflow;
      previousState.forEach(({ node, inert, ariaHidden }) => {
        (node as HTMLElement).inert = inert;
        if (ariaHidden === null) node.removeAttribute("aria-hidden");
        else node.setAttribute("aria-hidden", ariaHidden);
      });
      if (triggerRef.current && document.contains(triggerRef.current)) triggerRef.current.focus();
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className={overlayClassName}
      role="presentation"
      onMouseDown={(event) => {
        if (closeOnOverlay && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={describedBy}
        tabIndex={-1}
        className={className}
      >
        {title !== undefined && title !== null && showTitle ? <h2 id={titleId}>{title}</h2> : null}
        {children}
      </div>
    </div>,
    document.body,
  );
}

export default AccessibleDialog;
