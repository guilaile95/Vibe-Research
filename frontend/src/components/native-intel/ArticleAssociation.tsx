import type { NativeIntelItemEntity } from "@/lib/api";
import { articleAssociationDetail, articleAssociationText } from "@/lib/nativeIntelAssociation";

export function ArticleAssociation({ entities, className = "" }: {
  entities?: readonly NativeIntelItemEntity[];
  className?: string;
}) {
  return (
    <div className={`min-w-0 text-[11px] text-muted-foreground [overflow-wrap:anywhere] ${className}`} data-testid="article-association">
      <p>{articleAssociationText(entities)}</p>
      {!!entities?.length && (
        <details className="mt-1">
          <summary className="cursor-pointer hover:text-foreground">关联详情 · {entities.length} 条命中</summary>
          <p className="mt-1">来源为当前映射，不代表命中时来源。</p>
          <ul className="mt-1 space-y-1">
            {entities.map((entity, index) => <li key={index}>{articleAssociationDetail(entity)}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
