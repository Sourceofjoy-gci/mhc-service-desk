import { ArrowLeft, ShieldX } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

export default function PermissionPage() {
  return (
    <section className="mx-auto flex min-h-[60svh] max-w-2xl flex-col justify-center gap-6">
      <div className="flex items-center gap-3 text-sm font-medium text-destructive">
        <ShieldX className="size-5" aria-hidden />
        <span>403</span>
      </div>
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          Access not permitted
        </h1>
        <p className="max-w-xl text-sm leading-6 text-muted-foreground">
          Your account does not have permission to open this resource. If you
          believe this is incorrect, contact your service desk administrator.
        </p>
      </div>
      <Button
        render={<Link to="/login" />}
        nativeButton={false}
        variant="outline"
        className="w-fit"
      >
        <ArrowLeft data-icon="inline-start" />
        Return to sign-in
      </Button>
    </section>
  );
}
