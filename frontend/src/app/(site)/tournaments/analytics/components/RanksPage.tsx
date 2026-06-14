import React from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface TournamentRank {
  rank: string;
  damage: number;
  support: number;
}

interface Tournament {
  name: string;
  tournament: string;
  ranks: TournamentRank[];
}

const ranks: Tournament[] = [
  {
    name: "New Era x3",
    tournament: "Tournament 32",
    ranks: [
      {
        rank: "Чемпион1 - ГМ2",
        damage: 1,
        support: 3
      },
      {
        rank: "ГМ3 - ГМ4",
        damage: 2,
        support: 4
      },
      {
        rank: "ГМ5",
        damage: 3,
        support: 5
      },
      {
        rank: "М1",
        damage: 3,
        support: 5
      },
      {
        rank: "М2",
        damage: 4,
        support: 6
      },
      {
        rank: "М3",
        damage: 5,
        support: 7
      },
      {
        rank: "М4",
        damage: 6,
        support: 8
      },
      {
        rank: "М5",
        damage: 7,
        support: 9
      },
      {
        rank: "D1",
        damage: 8,
        support: 9
      },
      {
        rank: "D2",
        damage: 9,
        support: 10
      },
      {
        rank: "D3",
        damage: 10,
        support: 10
      },
      {
        rank: "D4",
        damage: 11,
        support: 11
      },
      {
        rank: "D5",
        damage: 12,
        support: 12
      },
      {
        rank: "P1",
        damage: 13,
        support: 13
      },
      {
        rank: "P2",
        damage: 14,
        support: 14
      },
      {
        rank: "P3",
        damage: 15,
        support: 15
      },
      {
        rank: "P4",
        damage: 16,
        support: 16
      },
      {
        rank: "P5",
        damage: 17,
        support: 16
      },
      {
        rank: "G1",
        damage: 18,
        support: 17
      },
      {
        rank: "G2",
        damage: 18,
        support: 17
      },
      {
        rank: "G3",
        damage: 19,
        support: 18
      },
      {
        rank: "G4",
        damage: 19,
        support: 19
      },
      {
        rank: "G5",
        damage: 19,
        support: 19
      },
      {
        rank: "S1",
        damage: 20,
        support: 19
      },
      {
        rank: "S2",
        damage: 20,
        support: 19
      },
      {
        rank: "S3",
        damage: 20,
        support: 20
      },
      {
        rank: "S4",
        damage: 20,
        support: 20
      },
      {
        rank: "S5",
        damage: 20,
        support: 20
      }
    ]
  },
  {
    name: "New Era x4",
    tournament: "Tournament 33",
    ranks: [
      {
        rank: "Чемпион1 - ГМ2",
        damage: 1,
        support: 2
      },
      {
        rank: "ГМ3 - ГМ4",
        damage: 2,
        support: 3
      },
      {
        rank: "ГМ5",
        damage: 3,
        support: 4
      },
      {
        rank: "М1",
        damage: 4,
        support: 5
      },
      {
        rank: "М2",
        damage: 5,
        support: 6
      },
      {
        rank: "М3",
        damage: 6,
        support: 7
      },
      {
        rank: "М4",
        damage: 7,
        support: 8
      },
      {
        rank: "М5",
        damage: 8,
        support: 9
      },
      {
        rank: "D1",
        damage: 9,
        support: 11
      },
      {
        rank: "D2",
        damage: 10,
        support: 12
      },
      {
        rank: "D3",
        damage: 12,
        support: 13
      },
      {
        rank: "D4",
        damage: 13,
        support: 14
      },
      {
        rank: "D5",
        damage: 14,
        support: 14
      },
      {
        rank: "P1",
        damage: 15,
        support: 15
      },
      {
        rank: "P2",
        damage: 15,
        support: 15
      },
      {
        rank: "P3",
        damage: 16,
        support: 16
      },
      {
        rank: "P4",
        damage: 16,
        support: 16
      },
      {
        rank: "P5",
        damage: 17,
        support: 16
      },
      {
        rank: "G1",
        damage: 18,
        support: 17
      },
      {
        rank: "G2",
        damage: 18,
        support: 17
      },
      {
        rank: "G3",
        damage: 19,
        support: 18
      },
      {
        rank: "G4",
        damage: 19,
        support: 18
      },
      {
        rank: "G5",
        damage: 19,
        support: 19
      },
      {
        rank: "S1",
        damage: 20,
        support: 19
      },
      {
        rank: "S2",
        damage: 20,
        support: 19
      },
      {
        rank: "S3",
        damage: 20,
        support: 10
      },
      {
        rank: "S4",
        damage: 20,
        support: 20
      },
      {
        rank: "S5",
        damage: 20,
        support: 20
      }
    ]
  }
];

const RanksPage = () => {
  return (
    <div className="grid gap-4 md:gap-8 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3">
      {ranks.map((tournament, index) => (
        <Card key={`tournament-${index}`}>
          <CardHeader className="space-y-1">
            <CardTitle className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="truncate" title={tournament.name}>
                {tournament.name}
              </span>
              <span className="text-sm font-normal text-muted-foreground">
                {tournament.tournament}
              </span>
            </CardTitle>
            <CardDescription>Division shift values by rank (damage/tank vs support).</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[180px] text-right">Rank</TableHead>
                  <TableHead className="text-center">Damage/Tank</TableHead>
                  <TableHead className="text-center">Support</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tournament.ranks.map((rank, rank_index) => (
                  <TableRow key={`rank-${index}-${rank_index}`}>
                    <TableCell className="font-medium text-right">{rank.rank}</TableCell>
                    <TableCell className="text-center tabular-nums">{rank.damage}</TableCell>
                    <TableCell className="text-center tabular-nums">{rank.support}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  );
};

export default RanksPage;
