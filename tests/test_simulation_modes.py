"""Régression : chaque carrefour (4 voies, rond-point) doit gérer une intervention d'urgence complète, télémétrie active."""
import math
import random
import unittest

from client.simulation import (CX, CY, EDGE, JUNCTIONS, RING_HALF, RING_ISLAND, SIDES, Simulation, Vehicle,
                               build_ring_path)


class ModesTest(unittest.TestCase):
    """Moteur de simulation : intervention d'urgence complète sur chaque type de carrefour, trajectoires du rond-point."""

    def lancer(self, nom, destination, vehicule="Ambulance"):
        """Joue une intervention complète sur le carrefour `nom` ; renvoie la simulation et les messages émis."""
        sim, messages = Simulation(), []
        sim.on_telemetry = messages.append
        sim.on_request = lambda payload, s=sim: s.grant_priority()
        sim.junction, sim.density = nom, 8
        sim.start()
        self.assertTrue(sim.spawn_emergency(vehicule, destination))
        sim.request_priority()
        for _ in range(600):
            sim.update(0.05)
        return sim, messages

    def test_chaque_carrefour_et_chaque_destination(self):
        for nom, cfg in JUNCTIONS.items():
            for destination in SIDES:
                with self.subTest(carrefour=nom, destination=destination):
                    sim, messages = self.lancer(nom, destination)
                    self.assertEqual(sim.interventions, 1)
                    types = {m["type"] for m in messages}
                    self.assertTrue({"session_start", "vehicle"} <= types)
                    # pas de feux à journaliser dans un rond-point
                    self.assertEqual("light_change" in types, cfg["mode"] == "lights")

    def test_chaque_type_de_vehicule_d_urgence(self):
        for vehicule in ("Ambulance", "Pompiers", "Police"):
            for nom in JUNCTIONS:
                with self.subTest(vehicule=vehicule, carrefour=nom):
                    sim, _ = self.lancer(nom, "Nord", vehicule)
                    self.assertEqual(sim.interventions, 1)

    def test_trajectoires_du_rond_point(self):
        """Les 12 trajectoires (voie normale et axe d'urgence) partent de leur branche et sortent vers la bonne."""
        for origine in SIDES:
            for destination in SIDES:
                if origine == destination:
                    continue
                for decalage in (30, 0):
                    with self.subTest(origine=origine, destination=destination, decalage=decalage):
                        chemin = build_ring_path(origine, destination, decalage)
                        self.assertTrue(all(math.isfinite(c) for pt in chemin.pts for c in pt))
                        self.assertAlmostEqual(chemin.cum[1], EDGE - RING_HALF)   # début de la zone de croisement
                        self.assertLess(chemin.s_exit, chemin.length)
                        rayons = [math.dist((CX, CY), pt) for pt in chemin.box_points()]
                        self.assertLess(max(rayons), RING_HALF + 15)        # on reste dans l'emprise du rond-point
                        self.assertGreater(min(rayons), RING_ISLAND + 9)    # sans rouler sur l'îlot central

    def test_urgence_sans_bouton_les_vehicules_lui_cedent_le_passage(self):
        """Sans demande V2I, les véhicules repèrent l'urgence et lui laissent la voie : elle traverse vite, sans contact."""
        for nom in JUNCTIONS:
            for destination in SIDES:
                with self.subTest(carrefour=nom, destination=destination):
                    random.seed(7)
                    sim = Simulation()
                    sim.auto_request = False
                    sim.junction, sim.density = nom, 9
                    sim.start()
                    self.assertTrue(sim.spawn_emergency("Police", destination))
                    em, debut = sim.em, sim.t
                    for _ in range(400):
                        sim.update(0.05)
                        for o in sim.vehicles:
                            if o is not em:
                                self.assertGreaterEqual(math.dist((o.x, o.y), (em.x, em.y)), 15)
                        if em.crossed:
                            break
                    self.assertTrue(em.crossed)
                    self.assertLess(sim.t - debut, 10)      # sans cette règle : jusqu'à 50 s (feu rouge, file d'attente)
                    self.assertEqual(sim.interventions, 0)  # pas de demande V2I : rien n'est enregistré comme intervention

    def rond_point_vide(self):
        """Rond-point démarré avec un trafic minimal."""
        sim = Simulation()
        sim.junction, sim.density = "Rond-point", 1
        sim.start()
        sim.vehicles.clear()
        sim._spawn = lambda dt: None        # aucun autre trafic
        return sim

    def test_rond_point_vehicule_seul_ne_s_arrete_jamais(self):
        """Fluidité : sans véhicule devant lui, un véhicule traverse sans la moindre attente (quelle que soit sa route)."""
        for origine in SIDES:
            for destination in SIDES:
                if origine == destination:
                    continue
                with self.subTest(origine=origine, destination=destination):
                    sim = self.rond_point_vide()
                    v = Vehicle("car", origine, destination, "#fff", ring=True)
                    sim.vehicles.append(v)
                    for _ in range(1200):
                        sim.update(0.05)
                        if v.done:
                            break
                    self.assertTrue(v.done)
                    self.assertEqual(v.wait, 0)

    def test_rond_point_n_attend_pas_la_fin_du_trajet_d_un_autre(self):
        """Un véhicule déjà passé devant l'entrée suivante ne retient pas celui qui s'y présente."""
        sim = self.rond_point_vide()
        premier = Vehicle("car", "Ouest", "Nord", "#fff", ring=True)     # long virage à gauche autour de l'anneau
        sim.vehicles.append(premier)
        for _ in range(120):                                              # 6 s : il a passé l'entrée Sud et poursuit sa route
            sim.update(0.05)
        second = Vehicle("car", "Sud", "Nord", "#000", ring=True)
        sim.vehicles.append(second)
        for _ in range(1200):
            sim.update(0.05)
            if second.done:
                break
        self.assertTrue(second.done)
        self.assertLess(second.wait, 1.0)

    def test_rond_point_dense_sans_contact_ni_blocage(self):
        """Forte densité et véhicules d'urgence : aucun véhicule ne se superpose, aucun ne reste bloqué."""
        for graine in (1, 2, 3):
            with self.subTest(graine=graine):
                random.seed(graine)
                sim = Simulation()
                sim.on_request = lambda payload, s=sim: s.grant_priority()
                sim.junction, sim.density = "Rond-point", 10
                sim.start()
                pire_blocage = 0.0
                for i in range(3600):                                     # 3 minutes simulées
                    if i % 600 == 300 and sim.em is None:
                        sim.spawn_emergency("Pompiers", random.choice(SIDES))
                        sim.request_priority()
                    sim.update(0.05)
                    pire_blocage = max([pire_blocage] + [v.blocked for v in sim.vehicles])
                    for a in range(len(sim.vehicles)):
                        for b in range(a + 1, len(sim.vehicles)):
                            va, vb = sim.vehicles[a], sim.vehicles[b]
                            if va.origin != vb.origin:
                                self.assertGreaterEqual(math.dist((va.x, va.y), (vb.x, vb.y)), 15)
                self.assertLess(pire_blocage, 2.0)


if __name__ == "__main__":
    unittest.main()
