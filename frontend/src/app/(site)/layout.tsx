import React from "react";
import Header from "@/components/Header";
import { Footer } from "@/components/Footer";
import { Separator } from "@/components/ui/separator";

export default function SiteLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="w-full max-w-screen-3xl mt-6 mx-auto px-4 md:px-6 xl:px-10 h-full">
      <Header />
      <div className="flex w-full flex-col min-h-[95%]">
        <main className="flex flex-1 flex-col gap-4 pt-4 md:gap-8 md:pt-8">
          {children}
        </main>
      </div>
      <Separator className="mt-8" />
      <Footer />
    </div>
  );
}
