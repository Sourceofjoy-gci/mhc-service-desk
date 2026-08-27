import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";

export default function NotFoundPage() {
  return (
    <section className="mx-auto flex min-h-[calc(100dvh-12rem)] max-w-xl flex-col items-start justify-center gap-5 py-12">
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium text-muted-foreground">404</p>
        <h1 className="text-3xl font-semibold tracking-tight">
          Page not found
        </h1>
        <p className="text-pretty text-muted-foreground">
          The page you requested does not exist or may have moved.
        </p>
      </div>
      <Link to="/login" className={buttonVariants()}>
        Staff sign-in
        <ArrowRight data-icon="inline-end" />
      </Link>
    </section>
  );
}
