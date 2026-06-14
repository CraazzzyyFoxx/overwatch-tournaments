import { Suspense } from "react";

import UsersRedesignClient from "./_components/UsersRedesignClient";

const UsersPage = () => {
  return (
    <Suspense fallback={null}>
      <UsersRedesignClient />
    </Suspense>
  );
};

export default UsersPage;
