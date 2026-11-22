import { ChevronLeft, ChevronRight, Crosshair } from 'lucide-react';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { PageViewport, PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask, TextLayer } from 'pdfjs-dist';
import { Button } from '../../../components/Button.tsx';
import { ErrorState } from '../../../components/ErrorState.tsx';
import { LoadingState } from '../../../components/LoadingState.tsx';
import { extractedPdfBox, type PdfBox } from './pdfBoxes.ts';
import { t } from '../../../i18n/messages.ts';
import type { Cell } from '../../../services/apiTypes.ts';
import { getDocumentOriginal } from '../../../services/documentsService.ts';
import { cx } from '../../../utils/classNames.ts';
import { formatCount } from '../../../utils/format.ts';
import { locateOnPage, words } from './pdfLocate.ts';
import { SHEET_FOOTER, SHEET_SCROLLER, SHEET_SCROLLER_FILL } from './sheetLayout.ts';

/** Room kept around the page inside the box, in CSS px. */
const PAGE_GUTTER = 24;
/** How far above the highlight the page is scrolled to, in CSS px. */
const SCROLL_MARGIN = 48;
/** Room kept beside the page's text when it is fitted to the box, in PDF points. */
const TEXT_MARGIN = 12;

/** The left and right edge of a page's text, in PDF points; the whole page when it has none. */
function textSpan(items: readonly object[], view: number[]) {
  const placed = words(items);
  if (!placed.length) return { left: view[0], right: view[2] };
  return {
    left: Math.max(view[0], Math.min(...placed.map((item) => item.transform[4])) - TEXT_MARGIN),
    right: Math.min(view[2], Math.max(...placed.map((item) => item.transform[4] + item.width)) + TEXT_MARGIN),
  };
}

/** A box in PDF points as a rectangle on the rendered page, in CSS px. */
function onPage(box: PdfBox | null | undefined, viewport: PageViewport) {
  if (!box || !viewport) return null;
  const [x0, y0] = viewport.convertToViewportPoint(box.left, box.top);
  const [x1, y1] = viewport.convertToViewportPoint(box.right, box.bottom);
  return { left: Math.min(x0, x1), top: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0) };
}

/** Where the search for the active cell stands, and what it found on which page. */
interface Found {
  state: 'idle' | 'searching' | 'value' | 'position' | 'no-oz' | 'missing';
  /** `reading`: the reader's own box of an uploaded PDF; `text`: found in the page's text */
  via?: 'reading' | 'text';
  page?: number;
  position?: PdfBox | null;
  value?: PdfBox | null;
}

/** What the footer says about the search for the active cell. */
function statusText(found: Found, target: PdfTarget | null | undefined) {
  if (!target) return t('Select a cell in the table to find it in the PDF.');
  const column = target.column || target.reference || '';
  const values = { oz: target.oz ?? '', column, page: found.page ? formatCount(found.page) : '' };
  switch (found.state) {
    case 'searching':
      return target.oz ? t('Finding position {oz} in the PDF…', values) : t('Finding the cell in the PDF…');
    case 'value':
      return target.oz
        ? t('{column} of position {oz} is highlighted on page {page}.', values)
        : t('{column} is highlighted on page {page}.', values);
    case 'position':
      return t('Position {oz} is highlighted on page {page}. Its {column} is not printed there.', values);
    case 'no-oz':
      return t('This row has no position number, so it cannot be found in the PDF.');
    case 'missing':
      return t('Position {oz} is not in this PDF, so nothing is highlighted.', values);
    default:
      return '';
  }
}

/** The PDF to show: the uploaded original (pdfLinks.ts). */
export interface PdfSource {
  documentId: string;
  file: string;
  /** the page to open first (1 when not given) */
  page?: number;
}

/** The active cell to find: its row's position number, the cell, and whether it is that number. */
interface PdfTarget {
  oz: string | null;
  cell: Cell | null;
  isOz: boolean;
  reference: string | null;
  /** The column's header, which the footer names instead of the cell reference. */
  column?: string | null;
}

interface SheetPdfProps {
  source: PdfSource;
  target?: PdfTarget | null;
  fill?: boolean;
}

/**
 * The sheet's PDF view: the printed bill in the same box as the table, one page at a time,
 * fitted to the box's width, with the active cell highlighted. The position (its block from the
 * number down to the next position) is marked lightly and the cell's value strongly; when the
 * value is not printed, only the position is marked and the footer says so. An uploaded PDF
 * uses the cell's own reading box when the reader kept one. The text stays selectable.
 *
 * `target`: `{ oz, cell, isOz, reference }` of the active cell, or null. `fill`: the box is
 * full screen, so the page area takes all the height it is given (the page refits its width).
 */
export function SheetPdf({ source, target, fill = false }: SheetPdfProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const texts = useRef(new Map<number, readonly object[]>());
  const targetRef = useRef(target);
  const [loaded, setLoaded] = useState<{ pdfjs: typeof import('pdfjs-dist'); document: PDFDocumentProxy } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [width, setWidth] = useState(0);
  const [pageNumber, setPageNumber] = useState(source.page ?? 1);
  const [rendered, setRendered] = useState<{ pageNumber: number; viewport: PageViewport; textLeft: number } | null>(null);
  const [found, setFound] = useState<Found>({ state: 'idle' });

  useLayoutEffect(() => {
    targetRef.current = target;
  });

  const targetKey = useMemo(
    () =>
      target
        ? JSON.stringify([target.oz, target.isOz, target.reference, target.cell?.raw_value ?? null, target.cell?.source?.bbox ?? null])
        : '',
    [target],
  );

  // The box's width, to fit the page to it.
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

  // Open the PDF: the declared print by URL, or the uploaded original with the session's access.
  useEffect(() => {
    let cancelled = false;
    let task: PDFDocumentLoadingTask | undefined;
    const controller = new AbortController();
    setLoaded(null);
    setError(null);
    texts.current = new Map();
    (async () => {
      const pdfjs = await import('pdfjs-dist');
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
      const input = { data: new Uint8Array(await (await getDocumentOriginal(source.documentId, { signal: controller.signal })).arrayBuffer()) };
      if (cancelled) return;
      // Kept as hardening although pdf.js 6 has no eval path and no longer types this option.
      const params = { ...input, isEvalSupported: false };
      task = pdfjs.getDocument(params);
      const document = await task.promise;
      if (!cancelled) setLoaded({ pdfjs, document });
    })().catch((failure) => {
      if (!cancelled) setError(failure);
    });
    return () => {
      cancelled = true;
      controller.abort();
      task?.destroy?.()?.catch?.(() => {});
    };
  }, [source.documentId, attempt]);

  // Find the active cell: page by page until a page prints its position number.
  useEffect(() => {
    if (!loaded) return undefined;
    const current = targetRef.current;
    if (!current) {
      setFound({ state: 'idle' });
      return undefined;
    }
    let cancelled = false;
    setFound({ state: 'searching' });
    const { document } = loaded;
    const pageText = async (number: number) => {
      let items = texts.current.get(number);
      if (!items) {
        const page = await document.getPage(number);
        items = (await page.getTextContent()).items;
        texts.current.set(number, items);
      }
      return items;
    };
    (async (): Promise<Found | null> => {
      const bbox = current.cell?.source?.bbox;
      if (bbox && bbox.page_number >= 1 && bbox.page_number <= document.numPages) {
        const box = extractedPdfBox(bbox, await document.getPage(bbox.page_number));
        if (box) return { state: 'value', via: 'reading', page: bbox.page_number, position: null, value: box };
      }
      if (!current.oz) return { state: 'no-oz' };
      for (let number = 1; number <= document.numPages; number += 1) {
        const hit = locateOnPage(await pageText(number), current);
        if (cancelled) return null;
        if (hit) return { state: hit.valueFound ? 'value' : 'position', via: 'text', page: number, position: hit.position, value: hit.value };
      }
      return { state: 'missing' };
    })()
      .then((result) => {
        if (cancelled || !result) return;
        setFound(result);
        if (result.page) setPageNumber(result.page);
      })
      .catch((failure) => {
        if (!cancelled) setError(failure);
      });
    return () => {
      cancelled = true;
    };
  }, [loaded, targetKey]);

  // Draw the page and its selectable text.
  useEffect(() => {
    if (!loaded || !width) return undefined;
    let cancelled = false;
    let renderTask: RenderTask | undefined;
    let textLayer: TextLayer | undefined;
    (async () => {
      const page = await loaded.document.getPage(pageNumber);
      const text = await page.getTextContent();
      const canvas = canvasRef.current;
      const pageBox = pageRef.current;
      const textBox = textRef.current;
      // The page's elements are always rendered; they are gone only once unmounted (cancelled).
      if (cancelled || !canvas || !pageBox || !textBox) return;
      // Fit the printed text, not the paper, to the box's width: the margins scroll aside.
      const span = textSpan(text.items, page.view);
      const scale = Math.min(3, Math.max(0.5, (width - PAGE_GUTTER) / (span.right - span.left)));
      const viewport = page.getViewport({ scale });
      const [textLeft] = viewport.convertToViewportPoint(span.left, 0);
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
      textLayer = new loaded.pdfjs.TextLayer({ textContentSource: text, container: textBox, viewport });
      await Promise.all([renderTask.promise, textLayer.render()]);
      if (!cancelled) setRendered({ pageNumber, viewport, textLeft: Math.round(textLeft) });
    })().catch((failure) => {
      if (!cancelled && failure?.name !== 'RenderingCancelledException') setError(failure);
    });
    return () => {
      cancelled = true;
      renderTask?.cancel?.();
      textLayer?.cancel?.();
    };
  }, [loaded, width, pageNumber]);

  const shown = rendered?.pageNumber === pageNumber ? rendered : null;
  const foundPage = found.page;
  const onThisPage = shown && foundPage === pageNumber;
  const positionBox = onThisPage ? onPage(found.position, shown.viewport) : null;
  const valueBox = onThisPage ? onPage(found.value, shown.viewport) : null;

  // Once a page is drawn: its text's left edge to the box's left, the highlight (or the top) in view.
  const focusBox = valueBox ?? positionBox;
  const focusTop = focusBox ? Math.round(focusBox.top) : null;
  const textLeft = shown?.textLeft ?? null;
  useEffect(() => {
    if (textLeft === null) return;
    scrollerRef.current?.scrollTo?.({ top: focusTop === null ? 0 : Math.max(0, focusTop - SCROLL_MARGIN), left: textLeft });
  }, [textLeft, focusTop, targetKey, pageNumber]);

  const pages = loaded?.document.numPages ?? null;
  const label = t('{file}, the uploaded file', { file: source.file });

  let body = null;
  if (error) {
    body = (
      <div className="p-4">
        <ErrorState error={error} title={t('The PDF could not be shown')} onRetry={() => setAttempt((value) => value + 1)} />
      </div>
    );
  } else if (!shown) {
    body = <LoadingState variant="pdf" label={t('Loading the PDF…')} />;
  }

  return (
    <>
      <div ref={scrollerRef} className={cx(fill ? SHEET_SCROLLER_FILL : SHEET_SCROLLER, 'relative bg-sidebar')} aria-label={t('PDF view: {label}', { label })} role="region">
        <p className="sticky left-0 top-0 z-10 truncate border-b border-hairline bg-sidebar/95 px-4 py-1 text-caption text-ink-secondary">
          {label}
        </p>
        {body}
        <div className={cx('w-max p-4', !shown && 'invisible absolute')}>
          <div ref={pageRef} className="sheet-pdf-page relative mx-auto bg-surface shadow-sm">
            <canvas ref={canvasRef} role="img" aria-label={t('Page {page} of {file}', { page: formatCount(pageNumber), file: source.file })} />
            {positionBox && (
              <mark
                data-testid="pdf-position"
                aria-label={target?.oz ? t('Position {oz}', { oz: target.oz }) : t('Position')}
                className="pointer-events-none absolute z-[1] rounded-sm bg-accent/10 ring-1 ring-accent/50"
                style={positionBox}
              />
            )}
            {valueBox && (
              <mark
                data-testid="pdf-cell"
                aria-label={target?.reference ? t('Cell {reference}', { reference: target.reference }) : t('Cell')}
                className="pointer-events-none absolute z-[1] rounded-sm bg-accent/25 ring-2 ring-accent"
                style={valueBox}
              />
            )}
            <div ref={textRef} className="textLayer" />
          </div>
        </div>
      </div>
      <div className={SHEET_FOOTER}>
        <p role="status" className="min-w-0 flex-1 px-4 py-1 text-callout text-ink-secondary">
          {error ? '' : statusText(found, target)}
        </p>
        <nav aria-label={t('PDF pages')} className="ml-auto flex flex-wrap items-center gap-2 px-4 py-2">
          {foundPage && foundPage !== pageNumber && (
            <Button variant="ghost" icon={Crosshair} onPress={() => setPageNumber(foundPage)}>
              {t('Back to the cell')}
            </Button>
          )}
          <p className="text-callout tabular-nums text-ink-secondary">{pages ? t('Page {page} of {pages}', { page: formatCount(pageNumber), pages: formatCount(pages) }) : ''}</p>
          <Button icon={ChevronLeft} isDisabled={!pages || pageNumber <= 1} onPress={() => setPageNumber(pageNumber - 1)}>
            {t('Previous')}
          </Button>
          <Button icon={ChevronRight} iconPosition="end" isDisabled={!pages || pageNumber >= pages} onPress={() => setPageNumber(pageNumber + 1)}>
            {t('Next')}
          </Button>
        </nav>
      </div>
    </>
  );
}
