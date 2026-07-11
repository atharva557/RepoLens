export default function Card({ children, className = "", ...props }) {
  return (
    <div
      className={`bg-surface-container border border-outline-variant/30 rounded-lg overflow-hidden transition-all duration-200 hover:border-outline-variant/60 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
