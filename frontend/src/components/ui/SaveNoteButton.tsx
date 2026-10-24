import { useRef, useState } from "react";
import { Check, BookmarkPlus } from "lucide-react";
import { addNote } from "@/lib/notes";
import type { NoteResearchMetadata } from "@/lib/researchNote";

import type { NoteGeneration } from "@/lib/noteGeneration";

// 把一段 AI 结果存入「研究记录」（沉淀）。存本地、不上传。
export function SaveNoteButton({ kind, title, content, metadata, generation }: { kind: string; title: string; content: string; metadata?: NoteResearchMetadata; generation?: NoteGeneration }) {
  const identity = JSON.stringify([kind, title, content, metadata, generation]);
  const [savedIdentity, setSavedIdentity] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ identity: string; message: string } | null>(null);
  const pending = useRef(false);
  const [saving, setSaving] = useState(false);
  const saved = savedIdentity === identity;
  if (!content.trim()) return null;
  return (
    <>
    <button
      onClick={async () => {
        if (pending.current) return;
        pending.current = true; setSaving(true);
        try {
          await addNote(kind, title, content, metadata, generation);
          setSavedIdentity(identity);
          setFailure(null);
        } catch (error) {
          setFailure({ identity, message: error instanceof Error ? error.message : "研究记录保存失败" });
        } finally { pending.current = false; setSaving(false); }
      }}
      disabled={saved || saving}
      className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-60"
    >
      {saved ? (<><Check className="h-3.5 w-3.5" /> 已存入沉淀</>) : (<><BookmarkPlus className="h-3.5 w-3.5" /> 存入沉淀</>)}
    </button>
    {failure?.identity === identity && <span role="alert" className="ml-2 text-xs text-destructive">{failure.message}</span>}
    </>
  );
}
