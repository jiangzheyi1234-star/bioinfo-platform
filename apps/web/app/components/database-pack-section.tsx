"use client";

import { Copy, Database, ExternalLink, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";

import {
  databasePackManualText,
  databasePackRegistrationCommand,
  databasePackSizeText,
} from "./database-page-model";

import type { DatabasePack } from "./database-page-model";

type DatabasePackSectionProps = {
  packs: DatabasePack[];
  loading: boolean;
  error: string;
  onCopyText: (text: string) => void;
  onStartAddingFromPack: (packId: string) => void;
};

export function DatabasePackSection({
  packs,
  loading,
  error,
  onCopyText,
  onStartAddingFromPack,
}: DatabasePackSectionProps) {
  if (!loading && !error && packs.length === 0) {
    return null;
  }
  return (
    <section className="border-y border-slate-100 py-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
          <Database strokeWidth={1.5} className="h-4 w-4 text-blue-600" />
          <span>数据库包</span>
        </div>
        {loading ? <span className="text-xs text-slate-400">正在读取</span> : null}
      </div>
      {error ? <div className="py-1 text-sm text-red-600">{error}</div> : null}
      <div className="grid grid-cols-1 gap-3">
        {packs.map((pack) => (
          <article key={pack.packId} className="rounded-md border border-slate-200 bg-white px-4 py-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="truncate text-sm font-medium text-slate-900">{pack.name}</div>
                  <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600">
                    {pack.version}
                  </span>
                  <span className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700">
                    {pack.installedLayer}
                  </span>
                </div>
                <div className="mt-1 truncate font-mono text-xs text-slate-500">{pack.packId}</div>
                <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-slate-600 md:grid-cols-2">
                  <PackFact label="来源" value={pack.sourceUrl} />
                  <PackFact label="校验" value={pack.checksum} />
                  <PackFact label="大小" value={databasePackSizeText(pack)} />
                  <PackFact label="目标" value={pack.manualInstall.readyDirHint} />
                  <PackFact label="登记脚本" value={pack.registrationHandoff.scriptPath} />
                  <PackFact label="证据策略" value={pack.evidencePolicy.acceptedEvidenceType} />
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {pack.expectedFiles.slice(0, 10).map((item, index) => (
                    <span
                      key={`${pack.packId}-${item}-${index}`}
                      className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-500"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2 md:max-w-48 md:justify-end">
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 px-2 text-xs text-slate-600"
                  onClick={() => onCopyText(pack.sourceUrl)}
                >
                  <ExternalLink strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                  来源
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 px-2 text-xs text-slate-600"
                  onClick={() => onCopyText(databasePackManualText(pack))}
                >
                  <Copy strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                  手动步骤
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 px-2 text-xs text-slate-600"
                  onClick={() => onCopyText(databasePackRegistrationCommand(pack))}
                >
                  <Copy strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                  登记命令
                </Button>
                <Button
                  type="button"
                  className="h-8 px-2 text-xs"
                  onClick={() => onStartAddingFromPack(pack.packId)}
                >
                  <ShieldCheck strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                  手动登记
                </Button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function PackFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 truncate">
      <span className="text-slate-400">{label}: </span>
      <span className="font-mono text-slate-700">{value}</span>
    </div>
  );
}
