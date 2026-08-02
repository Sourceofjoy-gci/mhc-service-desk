import { cn } from "@/lib/utils";

interface BrandMarkProps {
  className?: string;
  size?: number;
}

export function BrandMark({ className, size = 28 }: BrandMarkProps) {
  return (
    <svg
      className={cn("shrink-0", className)}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="2"
        y="2"
        width="28"
        height="28"
        rx="6"
        className="fill-primary"
      />
      <path
        d="M9 22 L13 10 L16 18 L19 10 L23 22"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-primary-foreground"
      />
      <circle cx="16" cy="6.5" r="1.6" className="fill-gold" />
    </svg>
  );
}

interface BrandLockupProps {
  className?: string;
  size?: "sm" | "md" | "lg";
}

const BRAND_LOCKUP_SIZES = {
  sm: { mark: 24, text: "text-sm" },
  md: { mark: 28, text: "text-base" },
  lg: { mark: 36, text: "text-lg" },
} as const;

export function BrandLockup({ className, size = "md" }: BrandLockupProps) {
  const lockupSize = BRAND_LOCKUP_SIZES[size];

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <BrandMark size={lockupSize.mark} />
      <div className="flex flex-col leading-tight">
        <span className={cn("font-semibold tracking-tight", lockupSize.text)}>
          MHC Service Desk
        </span>
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Master of the High Court
        </span>
      </div>
    </div>
  );
}
