import type {
  NormalizedFileDraftEntry,
  NormalizedManifestDraftEntry,
} from '../components/IngestionManifestEditor';
import type {
  BootstrapManifestEntry,
  BootstrapManifestFileEntry,
} from '../services/bootstrapSubmissions';
import type { ManifestEntry } from '../services/ingestionBatches';
import type { BootstrapPendingUploadFile } from '../services/bootstrapUploadSession';

type SharedNonFileManifestEntry = Extract<ManifestEntry, { source_type: 'text' | 'url' }>;

interface BootstrapSubmissionManifestBuildResult {
  manifestEntries: BootstrapManifestEntry[];
  pendingUploadFiles: BootstrapPendingUploadFile[];
}

interface DirectIngestionManifestSplitResult {
  manifestEntries: ManifestEntry[];
  fileEntries: NormalizedFileDraftEntry[];
}

interface SplitNormalizedManifestDraftEntriesResult {
  nonFileEntries: SharedNonFileManifestEntry[];
  fileEntries: NormalizedFileDraftEntry[];
}

function splitNormalizedManifestDraftEntries(
  entries: NormalizedManifestDraftEntry[]
): SplitNormalizedManifestDraftEntriesResult {
  const nonFileEntries: SharedNonFileManifestEntry[] = [];
  const fileEntries: NormalizedFileDraftEntry[] = [];

  for (const entry of entries) {
    if (entry.sourceType === 'text') {
      nonFileEntries.push({
        source_type: 'text',
        entry_id: entry.id,
        title: entry.title,
        text: entry.text,
      });
      continue;
    }

    if (entry.sourceType === 'url') {
      nonFileEntries.push({
        source_type: 'url',
        entry_id: entry.id,
        title: entry.title,
        url: entry.url,
      });
      continue;
    }

    fileEntries.push(entry);
  }

  return { nonFileEntries, fileEntries };
}

export function buildBootstrapSubmissionManifestEntries(
  entries: NormalizedManifestDraftEntry[]
): BootstrapSubmissionManifestBuildResult {
  const { nonFileEntries, fileEntries } = splitNormalizedManifestDraftEntries(entries);
  const manifestEntries: BootstrapManifestEntry[] = [...nonFileEntries];
  const pendingUploadFiles: BootstrapPendingUploadFile[] = [];

  for (const entry of fileEntries) {
    const fileEntry: BootstrapManifestFileEntry = {
      source_type: 'file',
      entry_id: entry.id,
      title: entry.title,
      filename: entry.file.name,
      size_bytes: entry.file.size,
      content_type: entry.file.type || undefined,
    };
    manifestEntries.push(fileEntry);
    pendingUploadFiles.push({
      entry_id: entry.id,
      title: entry.title,
      file: entry.file,
    });
  }

  return { manifestEntries, pendingUploadFiles };
}

export function splitDirectIngestionManifestEntries(
  entries: NormalizedManifestDraftEntry[]
): DirectIngestionManifestSplitResult {
  const { nonFileEntries, fileEntries } = splitNormalizedManifestDraftEntries(entries);
  const manifestEntries: ManifestEntry[] = [...nonFileEntries];
  return { manifestEntries, fileEntries };
}
