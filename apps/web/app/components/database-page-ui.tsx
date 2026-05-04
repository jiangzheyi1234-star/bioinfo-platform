import { Database, Dna, SearchCode, ShieldCheck } from "lucide-react";

import type { DatabaseTemplate } from "./database-page-model";

export function templateIcon(template: DatabaseTemplate, className = "h-4 w-4") {
  if (template.icon === "amr") {
    return <ShieldCheck strokeWidth={1.5} className={className} />;
  }
  if (template.icon === "index") {
    return <SearchCode strokeWidth={1.5} className={className} />;
  }
  if (template.icon === "custom") {
    return <Database strokeWidth={1.5} className={className} />;
  }
  return <Dna strokeWidth={1.5} className={className} />;
}
