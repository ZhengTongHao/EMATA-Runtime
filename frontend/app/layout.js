import "./globals.css";

export const metadata = {
  title: "EMATA Console",
  description: "Enterprise Multi-Agent Task Assistant control plane.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
