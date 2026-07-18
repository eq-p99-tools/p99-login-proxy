import type React from "react";

import { tooltipProps } from "./tooltip";

export interface DataTableColumn<T> {
  key: string;
  header: React.ReactNode;
  /** Plain-text tooltip on the column header (`<th title>`). */
  headerTitle?: string;
  render: (row: T) => React.ReactNode;
  sortable?: boolean;
  className?: string;
  width?: number;
  align?: "left" | "center" | "right";
  cellTitle?: (row: T) => string | undefined;
}

export interface GroupHeaderCell {
  label: string;
  colSpan: number;
  title?: string;
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  selectedKey?: string | null;
  onSelect?: (key: string) => void;
  sortKey?: string | null;
  sortAsc?: boolean;
  onSort?: (key: string) => void;
  emptyMessage?: string;
  fill?: boolean;
  rowClassName?: (row: T) => string | undefined;
  groupHeader?: GroupHeaderCell[];
  className?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  selectedKey,
  onSelect,
  sortKey,
  sortAsc = true,
  onSort,
  emptyMessage = "No rows",
  fill = false,
  rowClassName,
  groupHeader,
  className = "",
}: DataTableProps<T>) {
  if (rows.length === 0) {
    return <p className="empty-state">{emptyMessage}</p>;
  }

  const tableMinWidth = columns.reduce((sum, col) => sum + (col.width ?? 0), 0);

  const colGroup = (
    <colgroup>
      {columns.map((col) => (
        <col key={col.key} style={col.width != null ? { width: col.width } : undefined} />
      ))}
    </colgroup>
  );

  const groupHeaderRow = groupHeader ? (
    <tr className="group-header-row">
      {groupHeader.map((cell, index) => (
        <th
          key={`group-${index}`}
          colSpan={cell.colSpan}
          className={cell.label ? "group-header-cell" : "group-header-spacer"}
          {...tooltipProps(cell.title)}
        >
          {cell.label}
        </th>
      ))}
    </tr>
  ) : null;

  const columnHeaderRow = (
    <tr className="column-header-row">
      {columns.map((col) => (
        <th
          key={col.key}
          className={col.className}
          {...tooltipProps(col.headerTitle)}
        >
          {col.sortable && onSort ? (
            <button
              type="button"
              className="th-sort"
              onClick={() => onSort(col.key)}
              aria-sort={sortKey === col.key ? (sortAsc ? "ascending" : "descending") : "none"}
            >
              {col.header}
              {sortKey === col.key ? (sortAsc ? " ▲" : " ▼") : null}
            </button>
          ) : (
            col.header
          )}
        </th>
      ))}
    </tr>
  );

  const body = (
    <tbody>
      {rows.map((row) => {
        const key = rowKey(row);
        const selected = selectedKey === key;
        const extraClass = rowClassName?.(row);
        return (
          <tr
            key={key}
            className={[selected ? "selected" : undefined, extraClass].filter(Boolean).join(" ") || undefined}
            onClick={onSelect ? () => onSelect(key) : undefined}
            tabIndex={onSelect ? 0 : undefined}
            onKeyDown={
              onSelect
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(key);
                    }
                  }
                : undefined
            }
          >
            {columns.map((col) => {
              const title = col.cellTitle?.(row);
              return (
                <td
                  key={col.key}
                  className={[
                    col.className,
                    col.align === "center" ? "cell-center" : undefined,
                  ]
                    .filter(Boolean)
                    .join(" ") || undefined}
                  {...tooltipProps(title)}
                >
                  {col.render(row)}
                </td>
              );
            })}
          </tr>
        );
      })}
    </tbody>
  );

  return (
    <div className={fill ? "data-table-wrap data-table-fill" : `data-table-wrap ${className}`.trim()}>
      <table
        className={groupHeader ? "data-table has-group-header" : "data-table"}
        style={tableMinWidth > 0 ? { minWidth: tableMinWidth } : undefined}
      >
        {colGroup}
        <thead>
          {groupHeaderRow}
          {columnHeaderRow}
        </thead>
        {body}
      </table>
    </div>
  );
}
