import { notFound } from "next/navigation";
import { FrontPage } from "@/components/Front";
import { editionBySlug, getPage, getSite } from "@/lib/data";

export const dynamicParams = false;

export function generateStaticParams() {
  const site = getSite();
  return site.editions.flatMap((e) => site.dates.map((date) => ({ edition: e.slug, date })));
}

export default async function EditionDay({ params }: { params: Promise<{ edition: string; date: string }> }) {
  const { edition: slug, date } = await params;
  const site = getSite();
  const edition = editionBySlug(slug);
  const page = edition && getPage(edition.code, date);
  if (!edition || !page) notFound();
  return <FrontPage site={site} edition={edition} page={page} />;
}
