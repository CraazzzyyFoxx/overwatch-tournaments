import { cn } from "@/lib/utils";

import styles from "./hero-steps.module.css";

/**
 * The organizer hero's three steps as one path: a node per step, a line
 * between them. The list itself numbers the steps for assistive tech, so the
 * nodes are hidden from it.
 */
export function HeroSteps({
  label,
  steps,
  className
}: Readonly<{
  label: string;
  steps: readonly { title: string; text: string }[];
  className?: string;
}>) {
  return (
    <ol aria-label={label} className={cn(styles.steps, className)}>
      {steps.map((step, index) => (
        <li key={step.title} className={styles.step}>
          <span aria-hidden className={styles.node}>
            {index + 1}
          </span>
          <b className="pt-[3px] font-display text-ui font-semibold leading-[1.4] text-[color:var(--aqt-fg)]">
            {step.title}
          </b>
          <p className="text-body leading-relaxed text-[color:var(--aqt-fg-muted)]">{step.text}</p>
        </li>
      ))}
    </ol>
  );
}
