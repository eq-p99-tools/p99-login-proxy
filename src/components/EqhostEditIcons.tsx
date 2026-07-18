interface IconProps {
  className?: string;
}

export function PencilIcon({ className = "" }: IconProps) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinejoin="round"
        d="M11.5 1.5 14.5 4.5 5 14H2v-3L11.5 1.5z"
      />
    </svg>
  );
}

export function CheckIcon({ className = "" }: IconProps) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 8.5 6 11.5 13 4.5"
      />
    </svg>
  );
}
