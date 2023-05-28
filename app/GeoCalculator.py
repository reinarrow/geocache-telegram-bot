import math

class GeoCalculator:
    @staticmethod
    def calculate_distance(coord1, coord2):
        """
        Calculate the Haversine distance.

        Parameters
        ----------
        coord1 : tuple of float
            (lat1, lon1)
        coord2 : tuple of float
            (lat2, lon2)

        Returns
        -------
        distance_in_km : float
        """
        lat1, lon1 = coord1
        lat2, lon2 = coord2
        radius = 6371  # km

        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat/2) * math.sin(dlat/2) +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon/2) * math.sin(dlon/2))
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = radius * c

        return distance

    @staticmethod
    def calculate_compass_bearing(coord1, coord2):
        """
        Calculate the compass bearing between two coordinates in degrees

        Parameters
        ----------
        coord1 : tuple of float
            (lat1, lon1)
        coord2 : tuple of float
            (lat2, lon2)

        Returns
        -------
        compass_bearing : float
            Compass bearing in degrees, from north
        """
        lat1, lon1 = coord1
        lat2, lon2 = coord2

        if (lat1, lon1) == (lat2, lon2):
            return 0

        dLon = math.radians(lon2 - lon1)

        y = math.sin(dLon) * math.cos(math.radians(lat2))
        x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
            math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)

        radians_bearing = math.atan2(y, x)

        # Now we have the initial bearing, but math.atan2() returns values from -π to +π, 
        # so we need to normalize the result by converting it to a compass bearing 
        # as it should be in the range 0° ... 360°
        compass_bearing = math.degrees(radians_bearing)
        compass_bearing = (compass_bearing + 360) % 360

        return round(compass_bearing)
    
    def convert_bearing_to_cardinal(bearing):
        """
        Convert bearing into cardinal direction (in Spanish)

        Parameters
        ----------
        bearing : float
            Bearing in degrees

        Returns
        -------
        cardinal_direction : str
            Cardinal direction in Spanish
        """
        directions = [
            'Norte', 'Nornoreste', 'Noreste', 'Estenoreste',
            'Este', 'Estesureste', 'Sureste', 'Sursureste',
            'Sur', 'Sursuroeste', 'Suroeste', 'Oestesuroeste',
            'Oeste', 'Oestenoroeste', 'Noroeste', 'Nornoroeste'
        ]
        
        index = round(bearing / 22.5)
        index %= 16

        return directions[index]

