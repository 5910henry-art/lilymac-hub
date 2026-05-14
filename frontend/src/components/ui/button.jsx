export function Button({ children, className = "", ...props }) {
  return (
    <button
      className={`
        px-4 py-2
        bg-gray-200
        text-gray-900
        font-semibold
        rounded-lg
        shadow-sm
        hover:bg-gray-300
        active:bg-gray-400
        transition-colors duration-200
        ${className}
      `}
      {...props}
    >
      {children}
    </button>
  );
}
