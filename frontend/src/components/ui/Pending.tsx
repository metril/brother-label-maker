/** Quality floor: "No skeleton-shimmer everywhere: use a quiet mono ···
 * placeholder for pending values." Used everywhere this app used to show a
 * shimmering skeleton box (font/tape/symbol lists loading, printer status
 * "checking…"). */
export function Pending({ className = "" }: { className?: string }) {
  return (
    <span role="status" aria-label="Loading" className={`pending-ellipsis text-[13px] ${className}`}>
      ···
    </span>
  );
}
