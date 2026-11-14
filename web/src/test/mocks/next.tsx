import { vi } from "vitest";

export const mockPush = vi.fn();
export const mockReplace = vi.fn();
export const mockBack = vi.fn();
export const mockRefresh = vi.fn();

let currentParams: Record<string, string> = {};
let currentSearch = new URLSearchParams();
let currentPathname = "/";

export function setMockParams(params: Record<string, string>) {
  currentParams = params;
}

export function setMockSearchParams(init: string | Record<string, string>) {
  currentSearch = new URLSearchParams(init);
}

export function setMockPathname(pathname: string) {
  currentPathname = pathname;
}

export function resetNextMocks() {
  mockPush.mockReset();
  mockReplace.mockReset();
  mockBack.mockReset();
  mockRefresh.mockReset();
  currentParams = {};
  currentSearch = new URLSearchParams();
  currentPathname = "/";
}

export function getNextNavigationMock() {
  return {
    useRouter: () => ({
      push: mockPush,
      replace: mockReplace,
      back: mockBack,
      refresh: mockRefresh,
      prefetch: vi.fn(),
    }),
    useParams: () => currentParams,
    useSearchParams: () => currentSearch,
    usePathname: () => currentPathname,
  };
}

