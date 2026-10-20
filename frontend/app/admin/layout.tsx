import { AdminShell } from "@/components/admin/AdminShell";
import { privateMetadata, sectionTitle } from "@/lib/site";

// El título de `/admin`; cada sección pone el suyo en su propio layout y la
// plantilla le suma "· Admin".
export const metadata = {
  ...privateMetadata("Resumen · Admin"),
  title: sectionTitle("Resumen · Admin", "%s · Admin · Sebasanálisis"),
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
