interface PasswordVisibilityIconProps {
  visible: boolean;
  className?: string;
}

/** Eye icon matching Python ``password_visibility.py`` (20×20, #c4c6cc stroke). */
export function PasswordVisibilityIcon({ visible, className = "" }: PasswordVisibilityIconProps) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 20 20"
      aria-hidden="true"
      focusable="false"
    >
      <ellipse cx="10" cy="10.5" rx="7" ry="4.5" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <ellipse cx="10" cy="10.5" rx="2" ry="2.5" fill="currentColor" stroke="none" />
      {!visible ? (
        <line x1="4" y1="5" x2="16" y2="15" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
      ) : null}
    </svg>
  );
}
