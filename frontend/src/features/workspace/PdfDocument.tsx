import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy, RenderTask, TextLayer } from 'pdfjs-dist';
import { Button } from '../../components/Button.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { LoadingState } from '../../components/LoadingState.tsx';
import { t } from '../../i18n/messages.ts';
import { getDocumentOriginal } from '../../services/documentsService.ts';
import { cx } from '../../utils/classNames.ts';
import { formatCount } from '../../utils/format.ts';

/** Room kept around the page inside the box, in CSS px. */
const PAGE_GUTTER = 32;
/** Marks a text layer span that holds the searched text. */
const HIT = ['rounded-sm', 'bg-warning/40'];

/** Pages that contain `query`, case-insensitively, from the text of every page. */
async function findPages(pdf: PDFDocumentProxy, query: string) {
  const needle = query.toLocaleLowerCase();
  const pages: number[] = [];
  for (let number = 1; number <= pdf.numPages; number += 1) {
    const content = await (await pdf.getPage(number)).getTextContent();
    const text = content.items.map((item) => ('str' in item ? item.str : '')).join(' ');
    if (text.toLocaleLowerCase().includes(needle)) pages.push(number);
  }
  return pages;
}

interface PdfDocumentProps {
  file: string;
  /** an uploaded original, read with the session's access */
  documentId?: string;
  /** a declared document served as a static file */
  url?: string;
  /** the page to open first (1 when not given) */
  page?: number;
}

/**
 * A PDF that is not a bill (an uploaded supporting document, or a declared source of a
 * position's evidence), one page at a time fitted to the box's width, with a search over its
 * text. `documentId` or `url` says where it is read from.
 */
export function PdfDocument({ file, documentId, url, page = 1 }: PdfDocumentProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState<{ pdfjs: typeof import('pdfjs-dist'); pdf: PDFDocumentProxy } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [width, setWidth] = useState(0);
  const [pageNumber, setPageNumber] = useState(page);
  const [shown, setShown] = useState(0);
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState<{ query: string; pages: number[] } | null>(null);

  useEffect(() => {
    const element = scrollerRef.current;
    if (!element) return undefined;
    const measure = () => setWidth(Math.floor(element.clientWidth || 640));
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    let destroy: (() => unknown) | undefined;
    setLoaded(null);
    setError(null);
    (async () => {
      const pdfjs = await import('pdfjs-dist');
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
      // One of the two is always given (see the props).
      const input = url ? { url } : { data: new Uint8Array(await (await getDocumentOriginal(documentId!, { signal: controller.signal })).arrayBuffer()) };
      if (cancelled) return;
      // Kept as hardening although pdf.js 6 has no eval path and no longer types this option.
      const params = { ...input, isEvalSupported: false };
      const task = pdfjs.getDocument(params);
      destroy = () => task.destroy();
      const pdf = await task.promise;
      if (!cancelled) setLoaded({ pdfjs, pdf });
    })().catch((failure) => {
      if (!cancelled) setError(failure);
    });
    return () => {
      cancelled = true;
      controller.abort();
      Promise.resolve(destroy?.()).catch(() => {});
    };
  }, [documentId, url, attempt]);

  const hitQuery = search?.pages.length ? search.query.toLocaleLowerCase() : '';
  useEffect(() => {
    if (!loaded || !width) return undefined;
    let cancelled = false;
    let renderTask: RenderTask | undefined;
    let textLayer: TextLayer | undefined;
    (async () => {
      const page = await loaded.pdf.getPage(pageNumber);
      const canvas = canvasRef.current;
      const pageBox = pageRef.current;
      const textBox = textRef.current;
      if (cancelled || !canvas || !pageBox || !textBox) return;
      const [x0, , x1] = page.view;
      const scale = Math.min(2.5, Math.max(0.5, (width - PAGE_GUTTER) / (x1 - x0)));
      const viewport = page.getViewport({ scale });
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.ceil(viewport.width * dpr);
      canvas.height = Math.ceil(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      pageBox.style.width = `${viewport.width}px`;
      pageBox.style.height = `${viewport.height}px`;
      pageBox.style.setProperty('--total-scale-factor', String(scale));
      textBox.replaceChildren();
      renderTask = page.render({ canvas, canvasContext: canvas.getContext('2d') ?? undefined, viewport, transform: [dpr, 0, 0, dpr, 0, 0] });
      textLayer = new loaded.pdfjs.TextLayer({ textContentSource: await page.getTextContent(), container: textBox, viewport });
      await Promise.all([renderTask.promise, textLayer.render()]);
      if (cancelled) return;
      if (hitQuery) {
        for (const span of textBox.querySelectorAll('span')) {
          if (span.textContent?.toLocaleLowerCase().includes(hitQuery)) span.classList.add(...HIT);
        }
      }
      setShown(pageNumber);
    })().catch((failure) => {
      if (!cancelled && failure?.name !== 'RenderingCancelledException') setError(failure);
    });
    return () => {
      cancelled = true;
      renderTask?.cancel?.();
      textLayer?.cancel?.();
    };
  }, [loaded, width, pageNumber, hitQuery]);

  useEffect(() => {
    scrollerRef.current?.scrollTo?.({ top: 0 });
  }, [pageNumber]);

  const pages = loaded?.pdf.numPages ?? null;
  const runSearch = async () => {
    const text = query.trim();
    if (!loaded || !text) {
      setSearch(null);
      return;
    }
    const found = await findPages(loaded.pdf, text);
    setSearch({ query: text, pages: found });
    if (found.length) setPageNumber(found.find((page) => page >= pageNumber) ?? found[0]);
  };
  const nextHit = search?.pages.find((page) => page > pageNumber) ?? search?.pages[0];

  let searchText = '';
  if (search && !search.pages.length) searchText = t('“{query}” is not in this document.', { query: search.query });
  else if (search) {
    searchText = t('“{query}” is on {count} of {pages} pages: {list}.', {
      query: search.query,
      count: formatCount(search.pages.length),
      pages: formatCount(pages ?? 0),
      list: search.pages.map(formatCount).join(', '),
    });
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-2">
        <form
          role="search"
          className="flex min-w-0 flex-1 items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void runSearch();
          }}
        >
          <label className="flex min-w-0 max-w-sm flex-1 items-center gap-2 rounded-md border border-hairline-strong bg-surface px-2.5 py-1.5 focus-within:border-accent">
            <Search aria-hidden="true" className="size-4 shrink-0 text-ink-tertiary" />
            <span className="sr-only">{t('Search in the document')}</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('Search in the document')}
              disabled={!loaded}
              className="min-w-0 flex-1 bg-transparent text-callout text-ink outline-none placeholder:text-ink-tertiary"
            />
          </label>
          <Button type="submit" isDisabled={!loaded}>
            {t('Find')}
          </Button>
          {search && search.pages.length > 1 && nextHit && (
            <Button variant="ghost" onPress={() => setPageNumber(nextHit)}>
              {t('Next page with it')}
            </Button>
          )}
        </form>
        <p role="status" className="min-w-0 text-callout text-ink-secondary">
          {searchText}
        </p>
      </div>
      <div ref={scrollerRef} role="region" aria-label={t('PDF view: {label}', { label: file })} className="relative min-h-[28rem] flex-1 overflow-auto bg-sidebar">
        {error ? (
          <div className="p-4">
            <ErrorState error={error} title={t('The PDF could not be shown')} onRetry={() => setAttempt((value) => value + 1)} />
          </div>
        ) : (
          shown !== pageNumber && <LoadingState variant="pdf" label={t('Loading the PDF…')} />
        )}
        <div className={cx('w-max p-4', shown !== pageNumber && 'invisible absolute')}>
          <div ref={pageRef} className="sheet-pdf-page relative mx-auto bg-surface shadow-sm">
            <canvas ref={canvasRef} role="img" aria-label={t('Page {page} of {file}', { page: formatCount(pageNumber), file })} />
            <div ref={textRef} className="textLayer" />
          </div>
        </div>
      </div>
      <nav aria-label={t('PDF pages')} className="flex flex-wrap items-center justify-end gap-2 border-t border-hairline px-4 py-2">
        <p className="text-callout tabular-nums text-ink-secondary">
          {pages ? t('Page {page} of {pages}', { page: formatCount(pageNumber), pages: formatCount(pages) }) : ''}
        </p>
        <Button icon={ChevronLeft} isDisabled={!pages || pageNumber <= 1} onPress={() => setPageNumber(pageNumber - 1)}>
          {t('Previous')}
        </Button>
        <Button icon={ChevronRight} iconPosition="end" isDisabled={!pages || pageNumber >= pages} onPress={() => setPageNumber(pageNumber + 1)}>
          {t('Next')}
        </Button>
      </nav>
    </>
  );
}
