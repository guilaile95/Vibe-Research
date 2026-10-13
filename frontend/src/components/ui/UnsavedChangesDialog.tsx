import { useEffect, useId, useRef } from "react";
import { useBlocker } from "react-router-dom";

export function useUnsavedChanges(dirty: boolean, saving: boolean) {
  const completed = useRef(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const id = useId();
  const blocker = useBlocker(({ currentLocation, nextLocation }) => !completed.current && (dirty || saving) && (
    currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search
  ));
  useEffect(() => {
    if (blocker.state === "blocked") dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [blocker.state]);
  useEffect(() => {
    if (!dirty && !saving) return;
    const warn = (event: BeforeUnloadEvent) => {
      if (completed.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, saving]);
  const stay = () => { if (blocker.state === "blocked") blocker.reset(); };
  return {
    complete: () => { completed.current = true; },
    dialog: blocker.state === "blocked" && <dialog ref={dialogRef} aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`}
      className="m-auto w-11/12 max-w-md rounded-lg border border-border bg-background p-5 text-foreground shadow-xl backdrop:bg-black/50"
      onCancel={(event) => { event.preventDefault(); stay(); }}>
      <h2 id={`${id}-title`} className="font-semibold">{saving ? "保存正在进行中" : "内容尚未保存"}</h2>
      <p id={`${id}-description`} className="mt-2 text-sm text-muted-foreground">{saving
        ? "保存请求正在处理中，请等待结果。关闭或刷新页面无法保证取消保存。"
        : "离开会丢失未保存的输入。可以留在此页继续编辑并保存。"}</p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" autoFocus className="rounded border border-primary/40 px-3 py-2 text-sm text-primary" onClick={stay}>留在此页</button>
        <button type="button" disabled={saving} className="rounded border border-border px-3 py-2 text-sm disabled:opacity-50"
          onClick={() => { if (!saving && blocker.state === "blocked") blocker.proceed(); }}>放弃未保存内容并离开</button>
      </div>
    </dialog>,
  };
}
