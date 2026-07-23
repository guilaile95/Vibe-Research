export interface PortfolioAdviceRestoreToken {
  kind: "restore";
  id: number;
  generationId: number;
}

export interface PortfolioAdviceGenerationToken {
  kind: "generation";
  id: number;
}

export class PortfolioAdviceRequestCoordinator {
  private restoreId = 0;
  private generationId = 0;

  beginRestore(isRunning: boolean): PortfolioAdviceRestoreToken | null {
    if (isRunning) return null;
    return {
      kind: "restore",
      id: ++this.restoreId,
      generationId: this.generationId,
    };
  }

  canApplyRestore(token: PortfolioAdviceRestoreToken, isRunning: boolean): boolean {
    return !isRunning
      && token.id === this.restoreId
      && token.generationId === this.generationId;
  }

  beginGeneration(isRunning: boolean): PortfolioAdviceGenerationToken | null {
    if (isRunning) return null;
    ++this.restoreId;
    return { kind: "generation", id: ++this.generationId };
  }

  canApplyGeneration(token: PortfolioAdviceGenerationToken): boolean {
    return token.id === this.generationId;
  }

  invalidate(): void {
    ++this.restoreId;
    ++this.generationId;
  }
}

export function requirePersistedPortfolioAdvice<T>(saved: T | null): T {
  if (saved === null) {
    throw new Error("持仓建议权威结果读取失败");
  }
  return saved;
}
