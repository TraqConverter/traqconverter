import { TableScroll } from "@/components/legal/LegalPage"
import { SUB_PROCESSORS } from "@/lib/subprocessors"

export default function SubProcessorTable() {
  return (
    <TableScroll>
      <table>
        <thead>
          <tr>
            <th>Provider</th>
            <th>What it does</th>
            <th>Location</th>
          </tr>
        </thead>
        <tbody>
          {SUB_PROCESSORS.map((p) => (
            <tr key={p.name}>
              <td>{p.name}</td>
              <td>{p.purpose}</td>
              <td>{p.location}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  )
}
