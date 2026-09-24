import { Suspense } from "react";

import UsersClient from "./components/index/UsersClient";

const UsersPage = () => {
  return (
    <Suspense fallback={null}>
      <UsersClient />
    </Suspense>
  );
};

export default UsersPage;
