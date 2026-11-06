import type { FolderInspection, StorageStatus } from "../../shared/types"

export interface StorageAction {
  allowed: boolean
  move: boolean
  /** Whether there are projects the singer could bring along. */
  offersMove: boolean
  label: string
  note: string
}

function projects(count: number): string {
  return `${count} project${count === 1 ? "" : "s"}`
}

function describeTarget(target: FolderInspection): string {
  if (!target.exists) return "Vocalika will create this folder."
  if (target.project_count) return `This folder already has ${projects(target.project_count)}.`
  return "This folder has no projects yet."
}

/** What confirming the storage dialog would do, given the folder typed into it. */
export function storageAction(
  status: StorageStatus,
  target: FolderInspection,
  wantMove: boolean,
): StorageAction {
  if (target.path === status.data_directory) {
    if (status.configured) {
      return { allowed: false, move: false, offersMove: false, label: "IN USE", note: "This is the folder in use." }
    }
    // First start in a folder that already holds a library: keep it there.
    return {
      allowed: true,
      move: false,
      offersMove: false,
      label: "USE THIS FOLDER",
      note: target.project_count
        ? `Your ${projects(target.project_count)} are already here.`
        : describeTarget(target),
    }
  }
  const offersMove = status.project_count > 0
  const move = offersMove && wantMove
  return {
    allowed: true,
    move,
    offersMove,
    label: move ? `MOVE ${projects(status.project_count).toUpperCase()}` : "USE THIS FOLDER",
    note: describeTarget(target),
  }
}
