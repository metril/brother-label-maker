import type { ReactNode } from "react";
import { errorText, fieldLabelText, helpText } from "./styles";

interface FieldProps {
  id: string;
  label: string;
  help?: string;
  error?: string | null;
  children: ReactNode;
  /** Rendered as a <legend> inside a <fieldset> instead of a <label for> --
   * for composite controls (segmented groups, repeatable rows) where no
   * single input owns the label. */
  as?: "label" | "legend";
}

/** Consistent label/help/error chrome around one form field -- every field
 * gets a real `<label for>` (or `<legend>` for group controls), help text
 * from the schema's own `description` (that's what it's there for), and an
 * inline `role="alert"` error when a client-side bound is violated. */
export function Field({ id, label, help, error, children, as = "label" }: FieldProps) {
  const labelEl =
    as === "legend" ? (
      <legend className={fieldLabelText}>{label}</legend>
    ) : (
      <label htmlFor={id} className={`${fieldLabelText} mb-1`}>
        {label}
      </label>
    );

  return (
    <div>
      {labelEl}
      {children}
      {error ? (
        <p role="alert" className={errorText}>
          {error}
        </p>
      ) : help ? (
        <p className={helpText}>{help}</p>
      ) : null}
    </div>
  );
}
