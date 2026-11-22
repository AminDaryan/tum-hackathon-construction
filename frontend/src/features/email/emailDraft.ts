/**
 * Email drafts to people outside the platform (the client, the planner, a subcontractor), built
 * from what the run found without any language model: a recipient, a subject and a plain-text
 * body. `EmailDraftButton` (EmailDraft.tsx) shows one for editing and hands it to the reviewer's
 * email app through a mailto: link, or to the clipboard.
 *
 * A draft from anywhere else (such as the assistant) is the same plain object:
 * `{ to: string, subject: string, body: string }`, `to` being addresses separated by commas.
 */
import { formatCount, formatDecimal } from '../../utils/format.ts';
import { t } from '../../i18n/messages.ts';
import { plainExplanation, positionsText } from '../risks/riskModel.ts';
import type { PriceFacts } from '../risks/pricing.ts';
import type { Risk } from '../../services/apiTypes.ts';

type Block = string | null | false | undefined;

/**
 * The longest mailto: link handed to the email app. Outlook on Windows and several browsers cut
 * links past about 2,000 characters, so a longer draft opens without its body, which goes to the
 * clipboard instead.
 */
export const MAILTO_MAX_LENGTH = 2000;

export interface EmailDraft {
  /** addresses separated by commas */
  to: string;
  subject: string;
  body: string;
}

const GREETING = 'Hello,';
const CLOSING = 'Kind regards';

function withUnit(value: string | null | undefined, unit: string | null | undefined): string | null {
  return value == null ? null : `${formatDecimal(value)}${unit ? ` ${unit}` : ''}`;
}

function quoted(billName: string | null) {
  return billName ? `the bill of quantities "${billName}"` : 'the bill of quantities';
}

/**
 * The position as the client knows it ("Position: 02.010 Concrete", "Quantity: 12.5 m3"), from
 * the sheet row. Never the bidder's prices: a bidder does not send them to the client while
 * tendering.
 */
function positionLines(facts: PriceFacts | null): string[] {
  if (!facts) return [];
  const lines: string[] = [];
  const name = [facts.itemCode, facts.description].filter(Boolean).join(' ');
  if (name) lines.push(`Position: ${name}`);
  const quantity = withUnit(facts.quantity, facts.unit);
  if (quantity) lines.push(`Quantity: ${quantity}`);
  return lines;
}

/**
 * A pricing risk is about the bidder's own prices: its title and explanation quote them, so a
 * draft to the client names only its short title.
 */
const isPricing = (risk: Risk) => risk.category === 'pricing';

/** The risk's title after the short title, unless it already starts with it. */
function headline(risk: Risk, topic: string) {
  if (!risk.title || isPricing(risk) || risk.title === topic) return topic;
  return risk.title.toLowerCase().startsWith(topic.toLowerCase()) ? risk.title : `${topic}: ${risk.title}`;
}

function paragraphs(...blocks: (Block | Block[])[]) {
  return blocks
    .map((block) => (Array.isArray(block) ? block.filter(Boolean).join('\n') : block))
    .filter(Boolean)
    .join('\n\n');
}

/**
 * A draft about one risk: which bill and position, what is wrong, and the question (or a request
 * to check and confirm the position when the risk has none).
 *
 */
export function riskEmailDraft({
  risk,
  title,
  facts = null,
  billName = null,
}: {
  risk: Risk;
  /** the short title shown for the risk */
  title?: string;
  /** the position's figures */
  facts?: PriceFacts | null;
  /** the file name of the bill */
  billName?: string | null;
}): EmailDraft {
  const where = positionsText(risk, 5);
  const code = facts?.itemCode ?? risk.positions?.[0]?.item_code ?? null;
  const topic = title || risk.title || 'A point in the bill';
  const subject = [`Question on ${billName || 'the bill of quantities'}`, code ? `${topic}, position ${code}` : topic].join(': ');
  const explanation = isPricing(risk) ? '' : plainExplanation(risk.why_risk_here);
  const missing = risk.missing_information ?? [];
  const multiple = (risk.positions_total ?? risk.positions?.length ?? 0) > 1;

  const body = paragraphs(
    GREETING,
    `While reviewing ${quoted(billName)}, we came across a point we would like to clarify with you.`,
    positionLines(facts),
    multiple && where ? `Positions concerned: ${where}` : null,
    [headline(risk, topic), explanation || null],
    risk.question ?? 'Could you please check this position and confirm it or send a corrected version?',
    missing.length ? ['To settle it, we are missing:', ...missing.map((item) => `- ${item}`)] : null,
    'Thank you in advance.',
    CLOSING,
  );
  return { to: '', subject, body };
}

/**
 * A draft about several risks (the risks shown in the list): one numbered point each with its
 * positions, explanation and question.
 *
 */
export function risksEmailDraft({
  risks,
  titleOf = (risk) => risk.title,
  billName = null,
}: {
  risks: Risk[];
  /** the short title shown for a risk */
  titleOf?: (risk: Risk) => string;
  billName?: string | null;
}): EmailDraft {
  const count = risks.length;
  const points = count === 1 ? 'one point' : `${formatCount(count)} points`;
  const items = risks.map((risk, index) => {
    const where = positionsText(risk, 5);
    const explanation = isPricing(risk) ? '' : plainExplanation(risk.why_risk_here);
    return [
      `${index + 1}. ${titleOf(risk) || risk.title}`,
      where ? `   Positions: ${where}` : null,
      explanation ? `   ${explanation}` : null,
      risk.question ? `   Question: ${risk.question}` : null,
    ];
  });
  const body = paragraphs(
    GREETING,
    `While reviewing ${quoted(billName)}, we came across ${points} we would like to clarify with you.`,
    ...items,
    count === 1
      ? 'Could you please answer it or send a corrected version of the bill?'
      : 'Could you please answer these points or send a corrected version of the bill?',
    'Thank you in advance.',
    CLOSING,
  );
  return { to: '', subject: `Questions on ${billName || 'the bill of quantities'} (${points})`, body };
}

/** A material of the supplier request: a reviewed bill quantity and the positions it adds up. */
interface SupplierGroup {
  description: string;
  quantity: string;
  unit: string;
  /** combined by the reviewer from several groups */
  reviewed: boolean;
  positions: {
    specification: string;
    context: string;
    tableName: string;
    code?: string | null;
    rowNumber?: number | null;
    quantity?: string | null;
  }[];
}

/** A supplier request from reviewed bill quantities; no rates or invented material breakdown. */
export function supplierEmailDraft({ groups, billName }: { groups: SupplierGroup[]; billName: string }): EmailDraft {
  return {
    to: '',
    subject: t('Supplier price request: {bill}', { bill: billName }),
    body: paragraphs(
      t('Hello,'),
      t('Please quote the following quantities for {bill}, with unit prices, delivery costs and availability. Confirm the specifications before supply.', { bill: billName }),
      t('These are bill position quantities, not a material take-off. Installation, waste and composite items need your review.'),
      ...groups.map((group, index) => [
        `${index + 1}. ${group.description}: ${formatDecimal(group.quantity)} ${group.unit}`,
        ...[...new Set(group.positions.map((position) => position.specification))],
        ...[...new Set(group.positions.map((position) => position.context))].filter(Boolean),
        t('Contributing positions: {positions}', { positions: group.positions.map((position) => `${position.tableName} / ${position.code || position.rowNumber}: ${formatDecimal(position.quantity)} ${group.unit}`).join('; ') }),
        group.reviewed ? t('Specifications combined by the reviewer. Please confirm equivalence.') : null,
      ]),
      t('Kind regards'),
    ),
  };
}

/** The addresses of `to` (commas or semicolons between them), each encoded but keeping its @. */
function recipients(to: string) {
  return String(to ?? '')
    .split(/[,;]/)
    .map((address) => address.trim())
    .filter(Boolean)
    .map((address) => encodeURIComponent(address).replaceAll('%40', '@'))
    .join(',');
}

/**
 * The mailto: link of a draft (RFC 6068): UTF-8 percent-encoding, line breaks as CRLF. When the
 * whole link is longer than {@link MAILTO_MAX_LENGTH}, the link leaves out the body
 * (`complete: false`) and the body has to reach the email app another way.
 */
export function mailtoLink({ to, subject, body }: EmailDraft): { href: string, complete: boolean } {
  const encode = (text: string) => encodeURIComponent(String(text ?? '').replace(/\r?\n/g, '\r\n'));
  const base = `mailto:${recipients(to)}`;
  const head = subject ? [`subject=${encode(subject)}`] : [];
  const full = [...head, ...(body ? [`body=${encode(body)}`] : [])];
  const href = full.length ? `${base}?${full.join('&')}` : base;
  if (href.length <= MAILTO_MAX_LENGTH) return { href, complete: true };
  return { href: head.length ? `${base}?${head.join('&')}` : base, complete: false };
}

/** The draft as one text to paste: recipient, subject, then the body. */
export function draftText({ to, subject, body }: EmailDraft): string {
  return paragraphs([to ? `To: ${to}` : null, subject ? `Subject: ${subject}` : null], body);
}
