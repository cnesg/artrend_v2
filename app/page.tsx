import { redirect } from "next/navigation";
import { getSite } from "@/lib/data";

export default function Home() {
  redirect(`/${getSite().editions[0].slug}`);
}
