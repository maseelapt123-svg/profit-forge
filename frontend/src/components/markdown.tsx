import { Text, View } from "react-native";

import { fonts, makeStyles } from "@/src/theme";

export function MarkdownLite({ text, testID = "ai-analysis-text" }: { text: string; testID?: string }) {
  const styles = useStyles();
  return (
    <View style={{ gap: 4 }} testID={testID}>
      {text.split("\n").map((line, i) => {
        const t = line.trim();
        if (!t) return <View key={i} style={{ height: 4 }} />;
        const heading = /^(#+\s|\*\*[^*]+\*\*:?$)/.test(t);
        const clean = t.replace(/^#+\s*/, "").replace(/^[-*]\s+/, "• ").replace(/`/g, "");
        const parts = clean.split(/(\*\*[^*]+\*\*)/g);
        return (
          <Text key={i} style={heading ? styles.mdHead : styles.mdText}>
            {parts.map((p, j) =>
              p.startsWith("**") && p.endsWith("**") ? (
                <Text key={j} style={styles.mdBold}>
                  {p.slice(2, -2)}
                </Text>
              ) : (
                p
              ),
            )}
          </Text>
        );
      })}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  mdHead: { color: c.brandPrimary, fontFamily: fonts.display, fontSize: 16, marginTop: 6 },
  mdText: { color: c.onSurfaceTertiary, fontFamily: fonts.text, fontSize: 14, lineHeight: 21 },
  mdBold: { color: c.onSurface, fontWeight: "700" },
}));
