import nextConfig from "eslint-config-next/core-web-vitals";

/** @type {import("eslint").Linter.Config[]} */
export default [
  ...nextConfig,
  {
    rules: {
      "react/react-in-jsx-scope": "off",
      "no-unused-vars": "off",
      "react/prop-types": "off",
      "react/no-unknown-property": "off",
      "no-redeclare": "off",
      "react-hooks/exhaustive-deps": "off",
      "no-undef": "off",
    },
  },
];
