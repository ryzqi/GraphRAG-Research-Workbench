/**
 * Extension data hooks based on SWR
 */
import {
  createExtension,
  deleteExtension,
  getExtensionTools,
  listExtensions,
  listStdioTemplates,
  updateExtension,
  type ToolExtensionCreate,
  type ToolExtensionUpdate,
} from '../../services/extensions';
import { useApiMutation, useApiQuery } from '../../lib/swr';

const NO_ID = '__none__';

const KEYS = {
  all: ['extensions'] as const,
  list: () => [...KEYS.all, 'list'] as const,
  detail: (id: string) => [...KEYS.all, 'detail', id] as const,
  tools: (id: string | undefined) => [...KEYS.all, 'tools', id ?? NO_ID] as const,
  stdioTemplates: () => [...KEYS.all, 'stdio-templates'] as const,
};

export function useExtensions() {
  return useApiQuery(KEYS.list(), () => listExtensions().then((res) => res.items));
}

export function useExtensionTools(extensionId: string | undefined) {
  return useApiQuery(
    extensionId ? KEYS.tools(extensionId) : null,
    extensionId ? () => getExtensionTools(extensionId) : null
  );
}

export function useStdioTemplates() {
  return useApiQuery(
    KEYS.stdioTemplates(),
    () => listStdioTemplates().then((res) => res.items)
  );
}

export function useCreateExtension() {
  return useApiMutation((data: ToolExtensionCreate) => createExtension(data), {
    onSuccess: async (_, __, { invalidate }) => {
      await invalidate([KEYS.list()]);
    },
  });
}

export function useUpdateExtension() {
  return useApiMutation(
    ({ id, data }: { id: string; data: ToolExtensionUpdate }) =>
      updateExtension(id, data),
    {
      onSuccess: async (_, { id }, { invalidate }) => {
        await invalidate([KEYS.list(), KEYS.detail(id), KEYS.tools(id)]);
      },
    }
  );
}

export function useDeleteExtension() {
  return useApiMutation((id: string) => deleteExtension(id), {
    onSuccess: async (_, id, { invalidate }) => {
      await invalidate([KEYS.list(), KEYS.detail(id), KEYS.tools(id)]);
    },
  });
}

export { KEYS as extensionKeys };
