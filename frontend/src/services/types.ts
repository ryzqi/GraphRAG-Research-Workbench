export interface PageMeta {
  skip: number;
  limit: number;
  total: number;
  has_more: boolean;
}

export interface ListResponse<T> {
  items: T[];
  page: PageMeta;
}

